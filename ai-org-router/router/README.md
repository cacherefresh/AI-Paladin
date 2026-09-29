# router/
The dispatcher. Classifies each incoming task (schemas/task.schema.json)
and decides: local | escalated | hybrid.

- classifier.py       - heuristic + local-model confidence scoring
- dispatch.py         - claims a node, sends the task, tracks status
- policy.yaml         - the invariant, the four postures, and defaults.lock_mode
                        (pin the node to one posture; enforced at the API, not
                        just in the UI)

Clients of this router: `ui/demo/index.html` (browser console) and
`paladin-vscode/` (status bar + panel, read-only). Both are dumb HTTP clients —
all logic and the egress guard live in the router process.

The sovereign posture is the one that is not a routing rule: it arms
security/egress_guard.py, so BIG-AI is not declined, it is unreachable.
