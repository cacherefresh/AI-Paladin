# AGENTS.md

Conventions for coding agents working in this repository. Read this before
creating files.

## Scratch notes go in `TEMPORARY/TEMP_NOTES.md`

Session-specific working notes - staging plans, window layouts for a demo,
"what I was about to do next", open questions - belong in
**`TEMPORARY/TEMP_NOTES.md`**, which is gitignored.

Do **not** scatter `NOTES.md`, `TODO.md`, `PLAN.md`, `SCRATCH.md` or dated
variants through the tree. Every such file is context a future session has to
read and weigh, and most of them are stale within days. One known location,
ignored by git, keeps that cost at zero.

**The rule in one line:** if it will be false next week, it goes in
`TEMPORARY/TEMP_NOTES.md`. If it will still be true, it goes in `docs/` and is
committed.

Concretely:

| Content | Where |
|---|---|
| A reusable runbook or procedure | `ai-org-router/docs/` — committed |
| Design intent, roadmap, honest limits | `ai-org-router/docs/ROADMAP.md` — committed |
| What a module does and why | its own `README.md` — committed |
| This session's staging notes, todo, layout | `TEMPORARY/TEMP_NOTES.md` — ignored |

If a scratch note turns out to be durable, move it into `docs/` and delete it
from the scratch file rather than leaving both.

## The gates are data, not prose

`router/keywords.yaml`, `router/policy.yaml` and `security/policies/` are
enforcement, not documentation. Do not edit them to make a test pass or a demo
read better, and never add a rule that a model is asked to honour rather than a
router is made to enforce. A gate a model can talk its way past is not a gate.

## Do not overstate enforcement

This repository sells containment, so its own claims are held to the standard
it sells. `security/egress_guard.py` is a **process-level** guard, not a host
firewall and not an air gap. Any wording that implies otherwise - in code
comments, docs, the demo runbook or the pitch deck - is a defect. When
describing what is enforced, state the scope and the limit in the same
sentence.
