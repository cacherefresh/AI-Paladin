"""
BIG-AI adapter.

This machine has no ANTHROPIC_API_KEY, so the adapter runs in SIMULATED mode
and says so - every token it produces is badged SIMULATED in the UI and every
event it emits carries simulated=True. The latency it reports is modelled,
not measured, and the UI labels it that way. Do not present the BIG-AI timing
number as a measurement.

What IS real in this leg:
  * the routing decision that sent work here
  * the payload - the adapter receives, and echoes back, the exact bytes the
    router staged for egress. The receipt is genuine.
  * the notification and audit records

Making it real: set nodes.bigai.backend to 'claude-api' in router/policy.yaml
and implement call_claude() below against the Anthropic SDK. The router does
not care which adapter answers.
"""

import time

from bus import metrics
from bus import notifications as bus
from security import egress_guard

# Modelled BIG-AI characteristics: a hosted frontier model on datacentre
# accelerators. Fast first token, ~80 tok/s sustained.
SIM_FIRST_TOKEN_S = 0.55
SIM_TOKENS_PER_S = 80.0


def _receipt(staged: dict) -> str:
    """What BIG-AI actually received. This part is not simulated."""
    lines = ["**Received payload receipt**", ""]
    lines.append("- prompt: %d bytes" % staged.get("prompt_bytes", 0))
    files = staged.get("files", [])
    if files:
        for f in files:
            lines.append("- `%s` lines %d-%d, %d bytes"
                         % (f["path"], f.get("start_line", 1),
                            f.get("end_line", 0), f["bytes"]))
    else:
        lines.append("- no files attached")
    lines.append("- **total: %d bytes left your network**"
                 % staged.get("total_bytes", 0))
    if staged.get("reduction_note"):
        lines.append("- minimised: %s" % staged["reduction_note"])
    return "\n".join(lines)


def _body(prompt: str, staged: dict) -> str:
    kind = staged.get("kind", "full")
    if kind == "minimal":
        approach = ("Working from the %d-byte slice only. With just this "
                    "window I can suggest the fix, but I cannot see callers, "
                    "tests, or types defined elsewhere - so treat the "
                    "suggestion as a starting point and verify locally."
                    % staged.get("total_bytes", 0))
    else:
        approach = ("Working from the full context that was staged: %d files, "
                    "%d bytes total." % (len(staged.get("files", [])),
                                         staged.get("total_bytes", 0)))

    return (
        "%s\n\n"
        "---\n\n"
        "**This is a simulated BIG-AI response.** No API key is configured on "
        "this node, so no request was actually sent to an external provider - "
        "the payload above is what *would* have been transmitted, itemised "
        "exactly as the router staged it.\n\n"
        "%s\n\n"
        "The routing decision, the payload construction, the disclosure "
        "window, and the audit trail are all live. Only the model response is "
        "stubbed. Configure `nodes.bigai.backend: claude-api` in "
        "`router/policy.yaml` to make this leg real.\n"
        % (_receipt(staged), approach)
    )


def run(prompt: str, cfg, task_id: str, staged: dict, speed: float = 1.0):
    """
    Stream a simulated BIG-AI response. Blocking; call it on a thread.
    `speed` scales the simulated token rate for demo pacing.
    """
    # A simulated adapter opens no socket, so the egress guard would never see
    # it. Under a sealed posture that would let the stub quietly "succeed" and
    # write a receipt for bytes that could not have moved - a lie in the audit
    # log, which is worse than no adapter at all. Ask the guard explicitly.
    egress_guard.assert_egress_allowed("BIG-AI gateway")

    started = time.time()
    bus.emit("phase", task_id=task_id, phase="thinking",
             detail="Payload in flight to BIG-AI gateway", node="bigai-gateway",
             simulated=True)

    time.sleep(SIM_FIRST_TOKEN_S)
    first_token_at = time.time()
    bus.emit("timing", task_id=task_id, metric="first_token_s",
             value=round(first_token_at - started, 2), node="bigai-gateway",
             simulated=True)

    text = _body(prompt, staged or {})

    # Stream by word at the modelled rate so the pacing difference is visible
    # next to the on-prem stream rather than asserted in a label.
    words = text.split(" ")
    delay = 1.0 / (SIM_TOKENS_PER_S * max(0.1, speed))
    for i, word in enumerate(words):
        piece = word + (" " if i < len(words) - 1 else "")
        bus.emit("token", task_id=task_id, text=piece, source="bigai",
                 simulated=True)
        time.sleep(delay)

    elapsed = time.time() - started
    ttft = round(first_token_at - started, 2)
    approx_tokens = int(len(text) / 4)

    bus.emit("phase", task_id=task_id, phase="idle", detail="Task complete",
             node="bigai-gateway", simulated=True)
    # Tokens billed by a hosted provider include everything you send, not just
    # what comes back. ~4 bytes/token is the usual working approximation.
    tokens_in = int((staged or {}).get("total_bytes", 0) / 4)
    metrics.record_usage("bigai", tokens_in, approx_tokens, elapsed, estimated=True)
    bus.emit("done", task_id=task_id, source="bigai", tokens_in=tokens_in,
             elapsed_s=round(elapsed, 2), first_token_s=ttft,
             tokens=approx_tokens,
             tokens_per_s=round(approx_tokens / max(0.001, elapsed - ttft), 1),
             node="bigai-gateway", simulated=True)

    return {
        "ok": True,
        "text": text,
        "elapsed_s": round(elapsed, 2),
        "first_token_s": ttft,
        "tokens": approx_tokens,
        "tokens_per_s": round(approx_tokens / max(0.001, elapsed - ttft), 1),
        "tokens_in": tokens_in,
        "simulated": True,
    }


def call_claude(prompt: str, cfg, task_id: str, staged: dict):
    """
    SEAM for the real leg.

    Implement against the Anthropic Messages API with streaming, emitting the
    same bus events this module emits (phase / token / timing / done) with
    simulated=False. Model ids to consider: claude-opus-5 for deep reasoning,
    claude-sonnet-5 for the fast path. Requires ANTHROPIC_API_KEY and the
    `anthropic` package, neither of which is present on this node.

    Consult the claude-api reference before implementing - do not guess
    parameter names, pricing, or streaming event shapes.

    Note that this leg needs no sealed-posture check of its own: it opens a
    real socket to api.anthropic.com, and under the sovereign posture
    security/egress_guard.py refuses that connection before the syscall.
    """
    raise NotImplementedError(
        "Real BIG-AI leg not configured. No ANTHROPIC_API_KEY on this node.")
