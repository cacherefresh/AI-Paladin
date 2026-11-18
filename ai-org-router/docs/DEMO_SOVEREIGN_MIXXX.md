# Sovereign demo — AI-Paladin against a real third-party codebase

A runbook for demonstrating the `sovereign` posture while doing genuine work on
a large C++ project you do not own: the [mixxx](https://github.com/mixxxdj/mixxx)
fork at `github.com/cacherefresh/mixxx`.

Companion to [`DEMO.md`](DEMO.md), which covers the seeded Alpha-IP corpus and
the three routing postures. This one is narrower and makes a single claim.

---

## The claim

> A 40,000-file codebase was read, reasoned about, and reviewed by a 24B model,
> and **not one byte left this machine** — provable from the guard's boot
> self-test, the audit log, and the host's own socket table.

That is the whole demo. There is deliberately no protected-IP theatre here:
mixxx is GPL, publicly readable, and gating keywords on it would be a costume.
The posture is the argument.

## What this demo does *not* claim

State these before anyone asks. The demo is stronger for it, and the alternative
is being corrected in the room.

- **It is not an air gap.** `security/egress_guard.py` is a process-level guard.
  It seals the AI-Paladin router process — which is where 100% of model traffic
  goes — and nothing else on the machine.
- **VS Code is not inside the perimeter.** Nor is the Ollama daemon, nor your
  browser. See the window table below for exactly where the boundary sits.
- **No AI-authored code is contributed.** mixxx expects human-written,
  human-reviewed work. In this demo the model **reviews a diff you wrote by
  hand**; it never authors a patch. That is a deliberate choice, not a
  limitation we are working around.

---

## The windows, and which of them are inside the perimeter

This is the part that confuses people watching, so lay it out first. You will
have **four windows** open (five if you count the editor you develop
AI-Paladin in — close that one).

```
┌──────────────────────────────────┬──────────────────────────────────┐
│  1. VS Code                      │  2. AI-Paladin console           │
│     cacherefresh/mixxx           │     browser → 127.0.0.1:8722     │
│     you write the diff here      │     mode bar · SEALED banner     │
│                                  │     prompt box · agent LEDs      │
│                                  │     ledger · audit drawers       │
├──────────────────────────────────┼──────────────────────────────────┤
│  3. Router terminal              │  4. Ollama terminal              │
│     ./run_demo.sh                │     ollama serve                 │
│     tail -f logs/server.log      │     dev-mistral-2 lives here     │
│     ← the guard self-test prints │                                  │
│       here. This is your proof.  │                                  │
└──────────────────────────────────┴──────────────────────────────────┘
```

| # | Window | OS process | Inside the egress guard? |
|---|---|---|---|
| 1 | VS Code, mixxx fork | `code` | **No.** Separate process. Harden it — see below. |
| 2 | AI-Paladin console | your browser | **No** — but it only ever speaks to `127.0.0.1:8722`. It is a dumb HTTP client; nothing is decided in it. |
| 3 | Router terminal | `python3 -m server.app` | **Yes. This is the guarded process**, and it is the only one that talks to a model. |
| 4 | Ollama | `ollama serve` | **No.** A separate daemon that can pull models from the internet. Do not run `ollama pull` mid-demo. |
| 5 | VS Code, AI-Paladin repo | `code` | No. **Close it before you start** — two VS Code windows on stage is the single easiest way to confuse an audience. |

> **Optional:** the `paladin-vscode/` extension puts the posture in VS Code's
> status bar, so the sealed state is visible in window 1 without switching to
> window 2. It is read-only — it cannot change the posture — and the webview it
> opens is *not* inside the egress guard. See `paladin-vscode/README.md`.

**The console is one window, not two.** The prompt box and the monitoring live
on the same page: composer at the bottom, node LEDs and session ledger on the
right rail, notifications and rules behind the two header buttons. If you want a
dedicated monitor view, open a **second browser window on the same URL** and
leave the Notifications drawer open in it — drawer state is per-client, so the
two windows stay independent.

---

## Preflight

```bash
# 1. Ollama up, with the three models resident
ollama serve                       # window 4
curl -s 127.0.0.1:11434/api/tags | grep -o '"name":"[^"]*"'
#   devstral-small-2:latest   14.8 GB   the engineer
#   qwen3:0.6b                522 MB    the clerk
#   all-minilm:latest         45 MB     the sentry

# 2. AI-Paladin up                 # window 3
cd ai-org-router
./run_demo.sh restart
tail -f logs/server.log            # leave this running — it is your proof surface
```

You are looking for this, and you should point at it on stage:

```
guard     egress self-test PASSED  (probe 192.0.2.1:443 (RFC 5737 TEST-NET-1, unroutable))
          [ok] socket-connect     connect() to 192.0.2.1:443 refused, no packet sent
          [ok] create-connection  urllib's create_connection() to 192.0.2.1:443 refused, no packet sent
          [ok] dns-resolution     getaddrinfo('example.com') refused, no packet sent
          [ok] loopback-permitted on-prem model reachable: loopback address
```

If it says `FAILED`, the `sovereign` mode becomes **unavailable** rather than
unenforced — that is the fail-closed behaviour working, and the demo stops until
it is fixed. Do not demo a posture whose guard did not verify.

### Harden VS Code — the demo is dishonest without this

VS Code is outside the guard, so if it is phoning home while you claim nothing
left the machine, you are wrong. In Settings (`Ctrl+,`):

| Setting | Value | Why |
|---|---|---|
| `telemetry.telemetryLevel` | `off` | VS Code reports usage by default |
| `update.mode` | `none` | update checks are outbound |
| `extensions.autoCheckUpdates` | `false` | so is the gallery |
| `extensions.autoUpdate` | `false` | " |
| Settings Sync | signed out | syncs to Microsoft |
| GitHub Copilot | disabled/uninstalled | it is the exact thing you are arguing against |

And do not run `git push`, `git fetch`, or `git pull` on the mixxx fork during
the demo. Those are egress, from a process the guard does not cover, and someone
in the room will notice.

---

## The demo (~8 minutes)

### 1. Show the posture *before* — 30 s

Open the console. The node boots in `slow`. There is **no blue bar** under the
mode bar, because there is no perimeter: in `slow`, egress is possible and the
guarantee is that a human is asked first.

### 2. Seal it — 30 s

Click **`sovereign — Nothing leaves this machine`**.

- A blue **`PERIMETER SEALED · loopback only (127.0.0.0/8, ::1, AF_UNIX)`** bar
  appears, tagged *guard verified at boot*.
- A `posture.sealed` notification lands in the drawer.
- The invariant chip in the header is **unchanged** — worth pointing out. The
  rules engine never depended on the posture.

Say the line: *in `slow`, a human decides not to send it. In `sovereign`, there
is nothing to decide.*

### 3. Write the change — by hand, in VS Code — 3 min

In window 1, make a small, real change to the mixxx fork. Something you would
actually open a PR for. Then:

```bash
cd "$MIXXX"                 # your cacherefresh/mixxx checkout
git diff > /tmp/mine.diff
cat /tmp/mine.diff          # keep it small — a screenful reads on stage
```

### 4. Have the sealed model review *your* code — 2 min

Copy the diff into the console's prompt box, prefixed with a review instruction:

```
Review this diff for correctness, lifecycle and ownership bugs. I wrote it by
hand — critique it, do not rewrite it. Point at specific lines.

<paste the diff here>
```

Watch the routing card. Because the posture is sealed, the decision comes back
**locked to on-prem** with the reason:

> *Posture 'sovereign' is sealed: no destination outside this machine is
> reachable. Executed on-prem.*

Then the on-prem LED walks its real states and `dev-mistral-2` answers at
~5 tok/s on 24 CPU cores. The states are derived from the actual token stream,
not a timer.

> **Length knob.** On-prem output is capped at 420 tokens (~85 s at 5 tok/s), a
> deliberate pacing choice. A thorough code review wants more room: raise
> `max_tokens` in `nodes/ollama_worker.py:run()` to ~900 and budget ~3 minutes
> of silence instead. Decide which you want *before* you are in front of people.

### 5. Prove nothing left — 2 min

Three independent surfaces, weakest to strongest:

**a. The audit drawer.** Open Notifications. `posture.sealed`, `routing.local`.
No `egress.approved`. Nothing was transmitted because nothing could be.

**b. The ledger** (right rail): `Bytes off-prem: 0 B`. The session ledger has
been counting since the first prompt.

**c. The host's own socket table** — this is the one that convinces engineers,
because it does not come from AI-Paladin at all:

```bash
PID=$(pgrep -f "server.app" | head -1)
ss -tnp state established | grep "pid=$PID" | grep -v '127\.0\.0\.1\|\[::1\]'
#   (no output — every connection this process holds is loopback)
```

Show the unfiltered version next to it so it is clear the process *has*
connections; they are simply all to itself.

### 6. Optional — the perimeter refuses out loud — 1 min

Still sealed, ask for something that needs live data:

> *What is the latest stable release of Qt and its changelog?*

The `retrieving` state fires, the guard refuses at the socket, an
`egress.blocked` notification lands at **critical**, and the model answers from
local knowledge only — visibly stale, which is the honest cost of the perimeter.

### 7. Close on the limit, not the claim

> "That guard covers the AI-Paladin process. VS Code is not inside it, and
> neither is Ollama. For a machine-wide guarantee you want a host firewall or a
> network namespace with no default route — that is the next ring, and it is on
> the roadmap. What I can prove today is that the component which talks to
> models cannot reach anything but this machine, and it proves that to itself
> every time it starts."

---

## Notes and gotchas

- **The diff goes in the prompt, not a corpus.** AI-Paladin's corpora
  (`router/classifier.py:CORPORA`) point at the seeded demo tree and the
  AI-Paladin working tree. The mixxx checkout is not indexed, which is fine for
  a diff review: the diff *is* the context. Adding the fork as a third corpus is
  a small change to `CORPORA` if you later want the IDF ranker pulling real
  mixxx source in as background.
- **A mixxx diff will not usually trip the keyword gate**, and it does not
  matter if it does — under `sovereign` the work is pinned on-prem either way.
  The only visible difference is which reason string the routing card shows.
- **Pin the posture if you want it hands-off.** Set `defaults.lock_mode:
  sovereign` in `router/policy.yaml` and the mode bar greys out; `/api/classify`
  returns `409` for any other mode, so it cannot be clicked — or `curl`'d —
  away mid-demo.
- **Deep link.** `http://127.0.0.1:8722/?mode=sovereign` opens straight into the
  sealed posture. Same code path as clicking, still audited, and `lock_mode`
  still overrides it.
- **Restarting resets the ledger** but not the audit log — `logs/*.jsonl` are
  append-only. Truncate them before a demo if you want clean counters on screen.
