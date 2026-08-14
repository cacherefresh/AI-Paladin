# brain/
Context layer. **Scaffolding only — not yet populated.** Design note:
[`docs/ROADMAP.md` §2 and §6](../docs/ROADMAP.md).

Not a shared store. It splits along the org chart, and the split is the
security control:

- memory/internal/   - the employee's recall. The whole repository, its history,
                       and the reasoning behind it. Read by dev-mistral-2 ONLY.
- memory/external/   - the contractor's recall. What already left the building
                       under an approved disclosure, and what came back.
                       Read by dev-mistral-2 AND BIG-AI.
- obsidian-vault/    - human-readable, git-versioned (decisions, runbooks,
                       specs, task-logs)

Two rules govern the split:

  1. Read down. Internal reads both stores; external reads only its own.
  2. No write crosses the boundary — in either direction. The router is the
     only writer, and it writes each store separately.

Rule 2 is a removal, not a restriction. An on-prem model authoring notes the
contractor can read is a declassification channel, gated or not; it is also
unnecessary, because BIG-AI's answers land in the external store on their own
and the employee reads down. With no write path, the boundary is enforceable
with filesystem permissions rather than application logic.

Two things the split does NOT solve, both detailed in ROADMAP §6: the external
store aggregates disclosures the gate only ever evaluated one at a time, and
anything the internal tier reads out of it is BIG-AI-authored text that must be
treated as untrusted input, never as instruction.
