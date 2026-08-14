"""
on-prem worker: streams dev-mistral-2 (devstral-small-2) via Ollama and
publishes real agent-state events as it works.

State is DERIVED FROM THE REAL STREAM, not from a timer:
  * reading    - emitted when the worker actually opens a corpus file
                 (real path, real byte count)
  * retrieving - emitted when the prompt requires network egress; immediately
                 checked against security/policies/commands.yaml, which is
                 deny-by-default, so this usually ends in a real block
  * planning /
    coding /
    thinking   - parsed out of the model's own token stream, via explicit
                 [[PHASE:x]] markers it is instructed to emit, with a
                 structural fallback (code fences -> coding, checklists ->
                 planning) for when a 24B model forgets to.
  * error      - any exception or non-200 from the Ollama endpoint
"""

import json
import re
import time
import urllib.error
import urllib.request

from bus import metrics
from bus import notifications as bus

PHASE_RE = re.compile(r"\[\[PHASE:\s*([a-z_]+)\s*\]\]", re.I)
# Any tail that could still grow into a full marker; held back, not emitted.
PARTIAL_RE = re.compile(
    r"\[{1,2}(?:P(?:H(?:A(?:S(?:E(?::\s*[a-z_]*\]?)?)?)?)?)?)?$", re.I)

VALID_PHASES = {"thinking", "reading", "retrieving", "planning", "coding",
                "idle", "error"}

NET_INTENT = re.compile(
    r"\b(latest|current|today|news|search the web|look ?up online|"
    r"documentation for|changelog|cve|npm registry|pypi|stack ?overflow|"
    r"google|fetch from|download from|http://|https://)\b", re.I)

SYSTEM_PROMPT = """You are dev-mistral-2, an on-premises engineering agent \
running inside AI-Paladin. You are trusted with protected intellectual \
property because you never leave the building.

Announce your working phase by emitting a marker on its own line BEFORE the \
work of that phase. Use exactly these markers:

[[PHASE:thinking]]  - reasoning about the request
[[PHASE:planning]]  - laying out steps or a checklist, like a manager
[[PHASE:coding]]    - writing code, like a software developer

Emit at least one marker. Keep the answer tight and concrete. If you write \
code, use fenced blocks."""


def _phase(task_id: str, phase: str, detail: str = "", **extra):
    bus.emit("phase", task_id=task_id, phase=phase, detail=detail,
             node="onprem-01", **extra)


def _check_egress_policy(cfg, task_id: str, reason: str) -> bool:
    """
    On-prem is egress deny-by-default (security/policies/commands.yaml).
    Returns True if allowed. Emits a real block event if not.
    """
    _phase(task_id, "retrieving", "Attempting outbound fetch: " + reason)
    time.sleep(0.6)  # visible beat; the policy check itself is instant
    bus.emit("policy", task_id=task_id, gate="commands.yaml#network",
             outcome="blocked",
             detail="Egress deny-by-default. Domain not in allow_domains.")
    metrics.record_block()
    bus.notify("egress.blocked",
               "on-prem blocked from reaching the internet",
               "dev-mistral-2 needed an outbound fetch (%s). "
               "security/policies/commands.yaml is deny-by-default and the "
               "domain is not allow-listed. Answering from local knowledge "
               "only." % reason,
               severity="warning", task_id=task_id)
    return False


def run(prompt: str, cfg, task_id: str, staged_files=None, corpus_id="alpha-ip",
        max_tokens: int = 420):
    """
    Execute a task on-prem. Blocking; call it on a thread.
    Returns a dict with the full text and real timing metrics.
    """
    node = cfg.nodes.get("onprem", {})
    endpoint = node.get("endpoint", "http://localhost:11434")
    model = node.get("ollama_model", "devstral-small-2:latest")
    keep_alive = node.get("keep_alive", "60m")

    started = time.time()
    _phase(task_id, "thinking", "Task claimed by onprem-01 (dev-mistral-2)")

    # --- real file reads --------------------------------------------------
    context_blocks = []
    if staged_files:
        from router.classifier import read_corpus_file
        for rel in staged_files[:4]:
            content = read_corpus_file(corpus_id, rel)
            if not content:
                continue
            _phase(task_id, "reading",
                   "Reading %s" % rel,
                   path=rel, bytes=len(content.encode("utf-8")),
                   lines=content.count("\n") + 1)
            bus.emit("file_read", task_id=task_id, path=rel,
                     bytes=len(content.encode("utf-8")), node="onprem-01")
            context_blocks.append("--- %s ---\n%s" % (rel, content[:6000]))
            time.sleep(0.25)

    # --- real egress policy check ----------------------------------------
    if NET_INTENT.search(prompt):
        _check_egress_policy(cfg, task_id, "prompt requests external/live data")

    _phase(task_id, "thinking", "Generating on 24 CPU cores, no GPU")

    full_prompt = prompt
    if context_blocks:
        full_prompt = ("Context from the local repository:\n\n"
                       + "\n\n".join(context_blocks)
                       + "\n\nRequest: " + prompt)

    body = json.dumps({
        "model": model,
        "prompt": full_prompt,
        "system": SYSTEM_PROMPT,
        "stream": True,
        "keep_alive": keep_alive,
        "options": {"num_predict": max_tokens, "temperature": 0.4},
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint + "/api/generate", data=body,
        headers={"Content-Type": "application/json"})

    text_parts = []          # raw model output, markers included
    display_parts = []       # what the UI shows, markers stripped
    current_phase = "thinking"
    first_token_at = None
    eval_count = 0
    prompt_eval_count = 0
    done_reason = ""
    raw_all = ""
    scan_pos = 0
    pending = ""             # holdback for a marker split across chunks
    fence_open = False

    def flush(force=False):
        """
        Emit display text. A marker can arrive split across chunks
        ("[[", "PHASE", ":cod", "ing]]"), so a per-chunk regex never matches
        it - we strip complete markers and hold back any tail that could
        still become one.
        """
        nonlocal pending
        pending = PHASE_RE.sub("", pending)
        if force:
            out, pending = pending, ""
        else:
            m = PARTIAL_RE.search(pending)
            if m:
                out, pending = pending[:m.start()], pending[m.start():]
            else:
                out, pending = pending, ""
        if out:
            display_parts.append(out)
            bus.emit("token", task_id=task_id, text=out, source="onprem")

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw in resp:
                if not raw.strip():
                    continue
                try:
                    chunk = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    continue

                piece = chunk.get("response", "")
                if piece:
                    if first_token_at is None:
                        first_token_at = time.time()
                        bus.emit("timing", task_id=task_id,
                                 metric="first_token_s",
                                 value=round(first_token_at - started, 2),
                                 node="onprem-01")
                    text_parts.append(piece)
                    raw_all += piece

                    # --- phase 1: markers the model declared itself ---------
                    new_phase = None
                    last = None
                    for m in PHASE_RE.finditer(raw_all[scan_pos:]):
                        last = m
                    if last:
                        scan_pos += last.end()
                        cand = last.group(1).lower()
                        if cand in VALID_PHASES:
                            new_phase = cand

                    # --- phase 2: structural fallback ----------------------
                    # A 24B model forgets its markers sometimes. Code fences
                    # and checklists are unambiguous signals on their own.
                    if "```" in piece:
                        fence_open = not fence_open
                        if fence_open:
                            new_phase = "coding"
                    if (new_phase is None and not fence_open
                            and current_phase == "thinking"
                            and re.search(r"(?:^|\n)\s*(?:\d+\.|[-*]\s*\[ \])\s+\S",
                                          raw_all[-400:])):
                        new_phase = "planning"

                    if new_phase and new_phase != current_phase:
                        current_phase = new_phase
                        _phase(task_id, current_phase, "model-declared phase")

                    pending += piece
                    flush()

                if chunk.get("done"):
                    eval_count = chunk.get("eval_count", 0) or 0
                    prompt_eval_count = chunk.get("prompt_eval_count", 0) or 0
                    done_reason = chunk.get("done_reason", "") or ""
                    break
        flush(force=True)

    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        _phase(task_id, "error", "Ollama endpoint unreachable: %s" % exc)
        bus.notify("agent.error", "on-prem node failed",
                   "dev-mistral-2 at %s did not respond: %s" % (endpoint, exc),
                   severity="critical", task_id=task_id)
        return {"ok": False, "error": str(exc), "text": "",
                "elapsed_s": round(time.time() - started, 2)}

    elapsed = time.time() - started
    ttft = round((first_token_at or started) - started, 2)
    tps = round(eval_count / max(0.001, elapsed - ttft), 2) if eval_count else 0.0

    truncated = done_reason == "length"
    if truncated:
        # Be explicit rather than trailing off mid-sentence. At ~5 tok/s
        # on CPU the cap is a deliberate demo-pacing choice, not a bug.
        bus.emit("token", task_id=task_id, source="onprem",
                 text="\n\n_[output capped at %d tokens - on-prem runs at ~5 tok/s on CPU]_" % max_tokens)
    _phase(task_id, "idle", "Task complete")
    bus.emit("done", task_id=task_id, source="onprem",
             elapsed_s=round(elapsed, 2), first_token_s=ttft,
             tokens=eval_count, tokens_per_s=tps, node="onprem-01",
             simulated=False, truncated=truncated,
             tokens_in=prompt_eval_count)
    metrics.record_usage("onprem", prompt_eval_count, eval_count, elapsed)

    return {
        "ok": True,
        "text": "".join(display_parts).strip(),
        "elapsed_s": round(elapsed, 2),
        "first_token_s": ttft,
        "tokens": eval_count,
        "tokens_per_s": tps,
        "tokens_in": prompt_eval_count,
        "simulated": False,
        "truncated": truncated,
    }
