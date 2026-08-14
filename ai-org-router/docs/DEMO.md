# AI-Paladin — VC demo runbook

A prompt arrives. Before any socket opens, a rules engine decides whether the
work is allowed to leave the building. Protected IP runs on-prem on
dev-mistral-2. Everything else is the user's choice, made with full disclosure
of exactly which bytes would leave.

## Run it

```bash
cd ai-org-router
./run_demo.sh              # start   (also: stop | restart)
# -> http://localhost:8722
```

Requires only `python3` + a running `ollama`. No venv, no pip, no build step —
the server is Python standard library only.

The launcher refuses to start if Ollama is not answering, and the server
re-pings the model every 10 minutes with `keep_alive: 60m`. This matters: a
cold load of the 15 GB model is ~35 s of dead air in front of an audience.

## The one rule

> **keyword match ⇒ on-prem. Always. Not overridable.**

Defined in [`router/policy.yaml`](../router/policy.yaml) as `invariant`,
enforced in [`router/dispatch.py`](../router/dispatch.py) *before* the mode is
consulted. The three modes only govern what happens to traffic that does
**not** match.

| Mode | Keyword match | No match |
|---|---|---|
| `slow` — Prefer on-prem | on-prem, locked | on-prem; escalation offered, never automatic |
| `fast` — Limit on-prem to Protected Alpha IP | on-prem, locked | BIG-AI, full payload, confirm gate |
| `superfast` — Risky | on-prem, locked | BIG-AI, **minimal** payload + disclosure window |

## Demo script (~6 minutes)

**1. Protected IP is pinned — try to make it leave, you can't.**
Set mode to `superfast — Risky` (the most permissive posture) and send:

> *Fix the loyalty discount bug in the pricing engine margin model*

The router pins it on-prem anyway. The chat shows a locked routing card
naming the terms that fired (`margin model`, `nightjar`, `alpha ip`, and the
`**/alpha-ip/**` path rule). The point: even in the riskiest mode, protected
IP does not move.

Watch the on-prem LED walk its real states — **thinking → reading → planning →
coding → idle** — while the answer streams at ~5 tok/s. The `reading` state
carries a real file path and byte count. The `planning`/`coding` transitions
come from markers the model emits in its own token stream.

**2. Clean code goes out — but only after you see exactly what leaves.**
Same mode, send:

> *truncate in string_helpers exceeds the limit, please fix*

No keyword match, so the egress gate opens: **"This will leave on-prem. Are you
sure?"** The disclosure window itemises the payload — one file, the
`truncate()` definition only, `L19–26`, 229 bytes of 851, **73 % withheld** —
with the exact text expanded on screen. Click *Keep it on-prem* first to show
zero bytes move. Send it the second time.

**3. The speed trade, measured not asserted.**
The latency card compares the two legs. On-prem is genuinely slower: ~5 tok/s
on 24 CPU cores with no GPU, ~60–90 s for a real answer. That is the honest
cost of the guarantee, and it is the number a customer is buying down.

**4. The perimeter holds outbound too.**
**Switch to `slow — Prefer on-prem` first.** This beat only works when the task
actually runs on-prem. The prompt below carries no protected keyword, so in
`fast` or `superfast` the router correctly sends it *out* to BIG-AI and you get
the egress gate instead of the block. That is the rules engine behaving
properly — but it is not the beat you want here.

In `slow` mode, send:

> *What is the latest stable release of Python and its changelog?*

The `retrieving` state fires, then the request is blocked against
`security/policies/commands.yaml` (egress deny-by-default), an
`egress.blocked` notification lands, and the model answers from local
knowledge only — visibly stale, which is the honest cost of the perimeter.

**5. The ledger — the slide a CFO cares about.**
Point at the **Session ledger** card on the right rail. It has been counting
since the first prompt: tasks pinned on-prem, distinct protected terms fired,
bytes withheld broken out by *why* they stayed, and a containment percentage.
Underneath it, BIG-AI consumption — tokens sent out and tokens returned,
counted separately because that is how hosted providers bill — and the share
of all tokens handled locally instead.

If asked about cost: rates are unset on purpose. Set `pricing:` in
`router/policy.yaml` to your contracted rate and the ledger computes spend and
avoided spend. We do not ship a vendor price list, because a stale one is
worse than none.

**6. Notifications & rules.** Open the two drawers. Every routing decision,
every egress approval, every block is a topic event, persisted to
`logs/notifications.jsonl`. The rules drawer shows the live keyword set and the
locked invariant.

## What is real and what is not

Be straight about this if asked — the honest version is more convincing than
the vague one.

**Real:** the routing decision; the keyword + path rules engine; the IDF file
ranker; the payload staging and byte accounting; the disclosure window
contents; the on-prem model, its output, and every latency number attached to
it; the agent states (file reads are real; phase changes are parsed from the
model's own stream); the notification bus and audit sinks; the egress policy
block.

**Not real:** the BIG-AI response. This node has no `ANTHROPIC_API_KEY`, so
[`bigai/simulated.py`](../bigai/simulated.py) streams a stub at a *modelled*
80 tok/s and is badged `SIMULATED` in the UI, with its latency labelled
"(modelled)". What it echoes back — the payload receipt — is genuine: those
are the exact bytes the router staged. Nothing is transmitted anywhere.

To make it real: set `nodes.bigai.backend: claude-api` in
`router/policy.yaml` and implement `bigai.simulated.call_claude()`. The router
does not care which adapter answers.

## Corpora

- **Seeded Alpha IP corpus** (default) — `demo/alpha-ip/nightjar/` holds fake
  proprietary code (pricing engine, scoring kernel), `demo/public-utils/` holds
  clean shareable code. Each file has one real planted bug.
- **This AI-Paladin working tree** — switch the Corpus dropdown to scan the
  live repo. Expect real locks: `server/app.py` genuinely contains the strings
  `ANTHROPIC_API_KEY` and `.env`, so the credentials rule fires correctly.
  The rules files themselves are excluded via `scan_exclude`, because a gate
  must not trip on its own definition of the gate.

## Not in the MVP

The boolean + fuzzy rules engine — `must_contain` / `cannot_contain` /
`any` / `all` / `and` / `or` / `not`, plus inexact matching so a one-character
misspelling (`nightjr`, `pricng engine`) still trips the gate. The schema is
sketched in `keywords.yaml` under `rules_engine_roadmap` and displayed in the
UI as roadmap. A reference Levenshtein implementation sits unused in
`router/rules.py:fuzzy_score()` so wiring it up is plumbing, not research.

Also deliberately mocked: the notification bus is in-process fan-out plus a
JSONL sink. Swapping it for NATS/Kafka is an adapter change.

## Files

```
router/keywords.yaml    the gate: protected terms, paths, exclusions
router/policy.yaml      the invariant + the three modes
router/rules.py         matching (MVP exact; fuzzy stubbed for post-MVP)
router/classifier.py    corpus index, IDF ranking, payload slicing
router/dispatch.py      the routing decision
nodes/ollama_worker.py  on-prem execution + real agent-state events
bigai/simulated.py      the escalation leg (simulated; seam for the real one)
bus/notifications.py    topics, fan-out, JSONL audit
server/app.py           stdlib HTTP server
ui/demo/index.html      the whole UI, one file
```
