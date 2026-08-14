# ai-org-router

A local-first AI router: cheap/routine tasks run on an on-prem Ollama node,
complex work escalates to Claude. Modeled like a company org chart —
use internal staff first, call in the outside specialist only when needed.

**Working demo:** `./run_demo.sh` → http://localhost:8722
See [docs/DEMO.md](docs/DEMO.md) for the runbook.

The routing invariant, enforced before any socket opens:

> **keyword match ⇒ on-prem. Always. Not overridable.**

Three postures govern only the traffic that does *not* match: `slow`
(prefer on-prem), `fast` (limit on-prem to Protected Alpha IP), and
`superfast` (minimal payload, full disclosure of every byte that leaves).

See docs/ for architecture, schemas/ for the task & node contracts.
