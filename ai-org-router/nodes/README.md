# nodes/
One heartbeat agent runs on every machine (schemas/node.schema.json).
Reports status to the router/UI on an interval.

- heartbeat_agent.py   - reports role, model, load, current task
- ollama_worker.py     - executes local-tier tasks against dev-mistral-2
