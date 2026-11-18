# HUMAN_C_SUITE_DOCUMENTATION

Executive-facing material for AI-Paladin. Everything here is generated from a
real run of the working prototype — no mockups, no illustrations.

## Contents

| File | What it is |
|---|---|
| `PITCH_DECK.html` | 21-slide deck, light business theme. Open in any browser. Arrow keys or space to navigate; the dots at the bottom jump to a slide. |
| `PITCH_DECK.pdf` | The same deck, A4 landscape, for emailing or printing. Regenerate after editing the HTML. |
| `screenshots/` | 13 captures of the live demo, 3120×1880 (retina). Application window only — no desktop, no browser chrome. |

## The screenshots

Captured in one continuous session against the running prototype, so the
latency card and counters accumulate coherently across the sequence.

| File | Beat |
|---|---|
| `01-router-idle` | Opening state: three modes, both nodes, the state legend |
| `02-protected-pinned-onprem` | Protected IP pinned on-prem **in the riskiest mode**, with the matched terms |
| `03-state-reading` | Agent reading a real file (real path, real byte count) |
| `04-state-planning` | Agent in the planning phase, working like a manager |
| `05-state-writing-code` | Agent writing code, streaming live |
| `06-onprem-answer-complete` | Finished on-prem answer with measured latency |
| `07-egress-gate-disclosure` | **"This will leave on-prem. Are you sure?"** — the full disclosure window |
| `08-egress-denied` | Denial: zero bytes transmitted |
| `09-latency-comparison-bigai` | Both latency bars populated: 58.2 s on-prem vs 2.2 s BIG-AI |
| `10-outbound-blocked` | The local agent's internet request blocked by policy |
| `11-notifications` | The audit topics — full lifecycle of one egress decision |
| `12-rules-engine` | Live keyword set, the locked invariant, and the roadmap |
| `13-session-ledger` | The ledger panel: IP protected and BIG-AI tokens consumed |

## The session ledger

Two counters run from the first prompt of a session, because the number that
matters is cumulative and cannot be backfilled:

- **IP protected** — tasks pinned on-prem, distinct protected terms fired, and
  bytes withheld, attributed to *why* they stayed: the invariant firing, the
  payload being minimised, or a human declining at the gate. Rolled up as a
  containment percentage.
- **BIG-AI consumption** — tokens sent out and tokens returned, counted
  separately, because hosted providers bill on both. Plus the share of all
  tokens handled locally instead.

Dollar figures appear only if you set your own contracted rates under
`pricing:` in `router/policy.yaml`. AI-Paladin deliberately ships no vendor
price list — a stale one is worse than none — so with rates unset the ledger
reports tokens and says so rather than guessing.

Raw records append to `logs/metrics.jsonl`.

## The hardware-scaling slide

"It is not a curve. It is a cliff." is generated from `bench/`, not authored.
The one measured bar is this machine, CPU-only, no GPU: 4.94 tok/s on a
15.18 GB model, which is 75.0 GB/s of effective memory bandwidth. The other
bars are a published model whose assumptions live in `bench/project.py`.

**No GPU was attached when these numbers were taken**, and the deck says so
prominently — that is the point of the slide. If you are asked whether the
GPU figures are measured, the answer is no, they are modelled, and the model
is in the repository for anyone to check.

Before quoting any GPU number, read `bench/README.md`. Short version: the
external 8 GB card is not currently visible to the machine, and even once it
is, 8 GB cannot hold a 15.18 GB model — expect ~1.3×, not a transformation.
The cliff is at full VRAM residency, which needs 16 GB minimum.

## Honesty note — read this before presenting

Slide 13 states which parts are live and which are simulated, and the UI badges
the simulated leg on screen. **Leave both in.** The BIG-AI response is stubbed
because this node has no API key; its latency is labelled *(modelled)* rather
than presented as measured. Everything constituting the product — the routing
decision, the rules engine, the on-prem model and its real timings, the payload
staging, the disclosure window, the audit trail — is genuinely running.

An investor who discovers an unlabelled simulation on their own will discount
everything else in the room. One who is told up front will credit the rest.

## Regenerating

Screenshots and PDF are produced by driving the live prototype in a headless
browser. Start the demo first (`./run_demo.sh` in `ai-org-router/`), then
re-run the capture. After editing `PITCH_DECK.html`, re-export the PDF via
your browser's Print → Save as PDF (A4, landscape, background graphics on).
