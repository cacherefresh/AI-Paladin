# Roadmap — planned, not built

Design notes for two capabilities we intend to build. **Nothing here is
implemented.** No code in this repository depends on anything on this page.
Recorded now so the architecture we ship today does not foreclose it.

Both items were chosen because they compound: loops are only affordable
because of the subagent tier, and loops are only *useful* with shared memory.
Neither is worth building alone.

---

## 1. Loops — iterate instead of answering once

**Today.** One shot. Prompt in, answer out. If the answer is wrong, the human
notices and re-prompts. The agent never sees the consequence of its own work.

**Goal.** A bounded plan → act → observe → repeat cycle: write the fix, run the
tests, read the failure, correct it, stop when green or when the budget is
spent.

### Why this is affordable here specifically

A naive loop on a 24B model at 4.94 tok/s is unusable — ten iterations of a
300-token answer is ten minutes of silence. The org chart is what makes it
viable: **the loop controller is not the engineer.**

| Loop responsibility | Who does it | Cost |
|---|---|---|
| Decide whether to continue | clerk (0.6B) | ~200 ms |
| Summarise a test failure | clerk (0.6B) | ~300 ms |
| Re-check the gate each turn | sentry (45 MB) | ~50 ms |
| Actually write code | engineer (24B) | ~60 s |

The expensive tier is woken only for the step that genuinely needs generation.
Everything else — control flow, triage, summarisation, gate re-evaluation —
runs on models that answer in milliseconds. A ten-iteration loop that calls the
engineer three times costs three minutes, not ten.

### What it needs

- **Hard budgets**: wall-clock, iteration count, and token ceilings, enforced
  by the router, not requested of the model.
- **An observation channel**: run the test suite, capture stdout/stderr, read
  the files that changed. Each of these is a tool call.
- **Every iteration re-enters the gate.** This is the security consequence and
  the reason this is a design note rather than a weekend project: a loop
  multiplies gate decisions by the iteration count. It is only safe because the
  gate is already cheap (18 ms) and deterministic. A loop must never become a
  path by which content that failed the gate on turn one leaks out on turn six
  in a different wording — so classification runs on *every* turn, over the
  full accumulated context, not just the initial prompt.
- **Anti-thrash state**: what has been tried and what failed, so the loop does
  not oscillate between two wrong answers.
- **A visible stop reason** on the UI: solved / budget exhausted / blocked by a
  gate / human interrupt. A loop that ends silently is worse than no loop.

### Explicit non-goals

Unbounded autonomy. No loop runs without a ceiling, and no loop acquires
permissions its single-shot equivalent would not have had.

---

## 2. Shared on-prem memory of the codebase

**Today.** Each task re-reads files from disk and ranks them lexically (IDF).
Nothing is remembered between tasks. Every task starts from zero.

**Goal.** A persistent, branch-aware, on-prem index of the codebase, shared by
every agent and every node — the `brain/` directory this repository already
scaffolds but does not yet populate.

### Branch awareness is the point

Two indexes, maintained separately:

- **`production`** — what customers are actually running.
- **`development`** — what is in flight.

That distinction is what makes the memory worth having rather than merely
convenient. It lets an agent answer questions no single-shot context window
can: *is this bug present in what shipped, or only on dev?* *Was this
refactor already attempted and reverted?* *What does the diff between these
branches actually change in behaviour?*

### It reuses what is already resident

The embedding model for this is **already loaded**: `all-minilm`, 45 MB,
18 ms per embedding, running on CPU. Indexing a repository is an offline batch
job against a model that is already paid for. No new dependency, no new
hardware, no per-token cost.

Pair it with the two halves the scaffolding already describes:

- `brain/memory/` — machine recall: embeddings, symbol graph, per-branch index.
- `brain/obsidian-vault/` — human-readable decisions and runbooks, git-versioned,
  so the *reasoning* behind a change survives, not only the change.

### The strategic argument — this is the slide that matters

BIG-AI is permitted to see a **285-byte slice**. The on-prem tier is permitted
to see **the entire repository, its history, and the reasoning behind every
decision in it.**

So the local model is not the weaker option that you tolerate for security
reasons. On the axis that actually determines answer quality on a mature
codebase — context — **it is the only option that can ever be well-informed**,
because it is the only one allowed to read everything. That gap widens every
day the system runs. The hosted model gets a keyhole; the local model gets the
building.

### Consequences we must design for

- **The index is protected IP.** An embedding index over proprietary source is
  a lossy but real representation of that source. It must live inside
  `protected_paths` from day one and must never be stageable for egress. This
  is not an afterthought — it is the first line of the design.
- **Staleness.** Invalidate on commit via a git hook; re-index incrementally.
  A confidently wrong memory is worse than no memory.
- **Multi-node coherence.** "Shared" means one index, many workers. Whoever
  owns writes owns invalidation.
- **Provenance on every recall.** A retrieved fact carries the file, the
  branch, and the commit it came from, so a human can check it.

---

## Sequencing

Memory first, loops second. A loop without memory repeats its own mistakes
across tasks; memory without loops still improves every single-shot answer.
Neither should start before the boolean/fuzzy rules engine is finished, because
both increase the number of gate evaluations and the gate should be complete
before it is put under that load.

---

## 3. Fleet shape — mesh grid vs. micro datacentre

**Planned, not built. No code here.** The question: for a team of 5 to 500
developers, do you give every developer a node (mesh), or pool
$100k–$300k of GPUs into one on-prem micro datacentre?

The answer is not one or the other, and the reason falls straight out of the
tiering we already measured.

### The physics that decides it: batching

A single inference stream is memory-bandwidth-bound — one token requires
reading every weight. Crucially, **that read is shared across concurrent
requests**. A GPU serving 20 developers at once reads the weights once and
serves all 20 from it. Aggregate throughput therefore scales close to linearly
with concurrency until the card becomes compute-bound.

A mesh node serving exactly one developer can never do this. It pays the full
weight-read for a single stream, every time.

### The economics that follow: utilisation

A developer issues on the order of tens of prompts a day. At ~30 s of compute
each, that is roughly **20–30 minutes of GPU time per 8-hour day — under 6%
utilisation.** In a mesh, you buy 100% of the hardware to use 6% of it. Pooling
converts that idle 94% into either fewer cards or faster answers for everyone.

### Where the crossover sits

Modelled in `bench/fleet.py`, as bands rather than false precision. Inputs:
mesh node $1.5k–$3k (16 GB+ VRAM, per the residency cliff), pooled GPU $8k–$15k,
30–40% cluster overhead, 15–25 developers served per pooled GPU, and a two-GPU
floor for redundancy.

**Crossover: ~14 developers.** Below that you are buying cluster capacity nobody
is using — at 5 desks a two-GPU floor works out to roughly $6.3k per developer
against ~$2.2k for a mesh node. Above it, pooled capex per head falls away and
the gap widens without limit.

| Team | Mesh capex | Pooled capex | GPUs |
|---|---|---|---|
| 5 | $8k–15k | $21k–42k | 2 |
| 25 | $38k–75k | $21k–42k | 2 |
| 100 | $150k–300k | $42k–147k | 4–7 |
| 500 | $750k–1,500k | $208k–714k | 20–34 |

### The honest part about the $100k–$300k envelope

At 500 seats the stated envelope holds **only at the favourable end of the
assumptions**. The unfavourable end is $714k — roughly 2.4× the ceiling.

The entire spread is driven by one parameter: **developers served per pooled
GPU**. It should be the first thing a pilot measures, before anyone signs a
purchase order. We would rather publish the sensitivity than quote the
flattering end of it.

![Cost per developer, mesh vs pooled](../bench/fleet_chart.svg)

*Capex per developer by team size. Shaded bands are the full assumption range;
lines are the midpoint. Generated by `bench/make_fleet_chart.py` from
`bench/fleet.json` — regenerate rather than edit.*

### Two procurement paths

Both are on the table, and they are genuinely different businesses:

- **Client-supplied hardware.** The customer buys their own GPUs; we supply the
  router, rules engine, models and subscriptions. Software margins, no working
  capital, no inventory, and it shortens the cycle with security teams who
  insist on owning the metal.
- **We supply the cluster.** We procure, integrate, certify and ship the micro
  datacentre as one appliance. Much larger deals, and it is what makes the
  hardware-refresh tier and the take-back channel work at all — but it is a
  hardware business, with the working capital and thinner blended margins that
  implies. Price it as such rather than pretending it is software.

### The recommended shape — and it is the org chart again

The tiering we already ship answers this cleanly, because the tiers have
opposite hardware profiles:

- **Mesh the perimeter.** The sentry (45 MB) and clerk (0.6B) run on *every*
  developer machine. They need no GPU at all, they answer in milliseconds, and
  the security decision must be made **before** anything leaves the developer's
  own machine — including before it crosses your own LAN. The gate belongs at
  the edge, on every node, always.
- **Pool the horsepower.** The engineer tier (24B and, later, larger) lives in
  the micro datacentre, batched across the team, upgraded centrally, and
  serving work that has *already* cleared a local gate.

So: **the router is meshed; the compute is centralised.** Nothing reaches the
cluster that a local, deterministic gate has not already cleared.

### The security trade, stated honestly

Pooling is not free from a containment standpoint, and we should say so:

- A mesh keeps each developer's code on their own machine. Smallest blast
  radius per node — but N times the attack surface and N times the patching
  burden.
- A micro datacentre is a **shared multi-tenant system**. Code crosses your own
  LAN to reach it, and a compromise of the cluster exposes many developers'
  work at once rather than one person's. That demands tenant isolation, per-tenant
  audit, and encryption in transit *inside* the perimeter — none of which the
  current single-node design needs.

This is why the gate stays meshed even when the compute centralises. The
cluster is a compute resource, not a trust boundary.

### Ties to the commercial model

The hardware-refresh tier feeds this directly: cards retired from the pooled
cluster are exactly the right specification to seed or refresh mesh nodes, and
the entry-tier appliance for smaller customers. One fleet, three lives.


---

## 4. Multi-site continuity

Full design note: **`security/disaster-recovery.md`**.

Summary: 15-minute RPO, two geographically separated sites (e.g. Baltimore and
Chicago — different power grids, weather systems and FEMA regions), append-only
replicas that a compromised node has no authority to alter.

Two points from that note worth carrying into any customer conversation:

- **Restore order is rules → audit → memory → compute.** A node that comes back
  before its gate does is a node with no perimeter.
- **Replication is egress.** Shipping protected IP between sites every fifteen
  minutes is protected material crossing a network. It is held to the same
  discipline as any other egress: encrypted, private, logged to the same audit
  topics, and restricted to declared destinations.

It is also the recovery half of the ransomware control already specified in
`security/monitors/behavioral_rules.yaml` — detection without recovery is half
a control.

---

## Scope note

Sections 1–4 are **roadmap, not product**. They do appear in the investor deck,
but only as a clearly-badged *Future endeavour* block placed **after** "The
honest inventory" — never interleaved with the proof slides.

That ordering is the point. The deck establishes what is built and measured,
states plainly what is simulated, and only then shows where it goes. Forward-
looking material presented before that line reads as a claim; presented after
it, it reads as a plan. These notes carry the full detail the slides compress.
