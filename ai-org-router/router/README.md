# router/
The dispatcher. Classifies each incoming task (schemas/task.schema.json)
and decides: local | escalated | hybrid.

- classifier.py       - heuristic + local-model confidence scoring
- dispatch.py         - claims a node, sends the task, tracks status
- policy.yaml         - per task-type rules (e.g. "security.audit -> always escalate")
