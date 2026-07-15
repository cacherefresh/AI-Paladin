# Executive metrics (computed from task records — no new instrumentation)
1. Active developers & their current/last tasks (from requested_by + node claims)
2. Tasks completed: local vs escalated vs hybrid (routing.tier)
3. Tokens: local vs cloud (output.tokens_used)
4. Estimated $ saved = (cloud price x local tokens that WOULD have gone to API)
   - especially loop-y subtasks: retries, drafts, log parsing, test triage
5. Memory reuse savings: context served from brain/memory instead of re-sent
6. Skills reuse: tasks resolved by an existing skill vs fresh reasoning
7. Security posture strip: gates fired, alerts, mean time to human review
