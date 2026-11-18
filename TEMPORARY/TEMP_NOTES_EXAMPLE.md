# RENAME this to TEMP_NOTES.md and start from here. 
# This file is a snap shot as of 11 /11/ 2026 and should never modify as it is the example to copy from below:
# -----begin below-----

# Scratch — sovereign posture / mixxx demo


**Gitignored.** Session staging only. Anything durable belongs in
`ai-org-router/docs/`. See `AGENTS.md`.

Last touched: 2026-08-15

---

## Where we are

**Done and awaiting your commit:**

- `sovereign` posture — 4th mode, arms `security/egress_guard.py`
- `defaults.lock_mode` — operator pin, enforced at the API not just the UI
- Two deck slides: Proof·08 (the before/after screenshots) and Proof·09
  (self-test + 409 receipt), plus Future endeavour 6/6 (the LAN ring)
- `docs/DEMO_SOVEREIGN_MIXXX.md` — the committed runbook
- `.gitignore`, `AGENTS.md`, this file
[text](TEMP_NOTES.md)
**Built:** `paladin-vscode/` — status bar + console panel, read-only, verified
against the live router (all five status states).

## Decisions taken (so a later session does not relitigate them)

| Question | Decision |
|---|---|
| Mode name | `sovereign`, not sealed/airgap/contained |
| Enforcement | socket guard **+ boot self-test**, fail-closed |
| Exit control | pinnable via `lock_mode`, audited by default, ships unlocked |
| LAN scope | loopback hard-coded for MVP; no config surface yet |
| Extension shape | thin webview client. Package split = future, well past MVP |
| Extension authority | **display only** — no posture writes from the editor |
| Demo thesis | posture alone. No keyword theatre on a GPL repo |
| Prompt type | model reviews Rob's hand-written diff; never authors |
| Notes | rTEMPORARY/TEMP_NOTES.mdunbook committed, this file ignored |
| Memory model | two stores, split by reader — ROADMAP §6 |
| Memory ACL | internal reads both; external reads external only |
| Memory writes | **none cross the boundary, either direction.** Router is sole writer |
| Live-fire branch | separate branch, router in front of Claude Code — ROADMAP §7 |

## Extension spec — draft, build next

`paladin-vscode/`, ~80 lines, no build step beyond `vsce package`.

```
package.json        engines.vscode, activationEvents, contributes.commands
extension.js        activate() → status bar item + one command
```

- **Status bar item**: poll `GET /api/posture` every 2 s.
  - sealed  → `$(shield) SEALED · loopback only`, `statusBarItem.warningBackground`
  - open    → `$(shield) <mode>`, no background
  - no router → `$(circle-slash) AI-Paladin offline`, dimmed
- **Click** → opens the console. Two options, pick when building:
  webview panel at `127.0.0.1:8722`, or `vscode.env.openExternal` to the
  browser. Webview is what was chosen; keep the browser fallback if the CSP
  fights us.
- **Command** `AI-Paladin: Open Console`. That is the whole surface.
- **No posture writes.** Decided. If someone asks for a "Seal" command later,
  the asymmetric version (arm yes, disarm no) is the one to build — it needs a
  direction-aware check in `POST /api/posture` server-side.
- Configuration: `aiPaladin.endpoint`, default `http://127.0.0.1:8722`.

Honesty note to carry into the extension README: the webview is **not** inside
the egress guard. It is a renderer in VS Code's process tree. It only talks to
loopback, but the Python guard has no visibility into it. Same wording
discipline as everywhere else.

## Roadmap decisions taken 2026-08-15

**§6 two-tier memory.** Rob's call, and it is stronger than the gated-write
version I first proposed: don't gate the internal→external channel, *remove*
it. BIG-AI's answer lands in the external store by itself and the internal
tier reads down, so knowledge flows upward for free and no declassification
path exists to get wrong. Same argument as sovereign-vs-slow: removing a
capability beats governing it. Bonus — enforceable with filesystem perms
instead of application logic.

Two open hazards written into §6 rather than solved:
- **Aggregation.** The gate is per-task; the external store is cumulative.
  Over months BIG-AI's context becomes the union of every approved slice.
  Answer: contractor engagements have a term — retention, a ceiling, and
  periodic re-gating of the *whole* store.
- **Injection.** Internal reading contractor notes = ingesting BIG-AI-authored
  text. Must be delimited, labelled untrusted, never instruction. Same rule as
  keywords.yaml applies to prompts.

**§7 live-fire branch.** Measurement, not a feature. The point is a
denominator we didn't choose — a month of real usage replaces the
demo-session token-share stat on the title slide. Mechanism already exists:
clerk triage + a PreToolUse hook. If the real numbers are worse than the demo
numbers, the real numbers ship.

## Open, needs Rob

- **Path to the mixxx fork** — runbook uses `$MIXXX` as a placeholder. If you
  want it added as a third corpus in `router/classifier.py:CORPORA`, I need the
  absolute path. Not required for the diff-review demo.
- **`max_tokens` for the demo** — 420 (≈85 s, may truncate a review) vs ~900
  (≈3 min of silence). Pick before rehearsal, edit `nodes/ollama_worker.py`.
- **PITCH_DECK.pdf is stale.** No headless-browser PDF path on this box that
  matches the deck's print CSS; needs your browser Print → Save as PDF, A4
  landscape, background graphics on.
- **`logs/*.jsonl` and `__pycache__/` are tracked in git** and my test runs
  dirtied them. `.gitignore` now covers pycache for *new* files but does not
  untrack existing ones. If you want them out:
  `git rm -r --cached ai-org-router/logs ai-org-router/**/__pycache__`
  — your call, it is a noisy diff.

## Rehearsal checklist

- [ ] Close the AI-Paladin VS Code window. Two editors on stage reads as a mess.
- [ ] VS Code hardening applied (telemetry off, no auto-update, Sync signed out,
      Copilot disabled) — runbook has the table
- [ ] `ollama serve` up, all three models resident, **no `ollama pull` mid-demo**
- [ ] Truncate `lTEMPORARY/TEMP_NOTES.mdogs/*.jsonl` for clean ledger counters
- [ ] Guard self-test says PASSED — if not, stop, do not demo it
- [ ] Have the small mixxx diff written and `git diff` saved *before* you start
- [ ] Decide: `max_tokens` 420 or 900
- [ ] Practise the `ss` verification command once; it is the strongest moment
      and fumbling it wastes it

## Lines that landed well while building

- "In `slow` a human decides not to send it. In `sovereign` there is nothing to
  decide."
- "BIG-AI is not declined. It is unreachable."
- "Resolving a name is itself a packet leaving."
- "A posture that cannot prove it blocks is a label."
- On the self-test's 4th check: "a guard that blocked everything would pass the
  first three while taking the local model offline with it."
