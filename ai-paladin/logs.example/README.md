# logs.example/

A frozen sample of what the router writes to `logs/` during a demo, for anyone
reading the docs or the pitch deck without running it.

| File | What it records |
|---|---|
| `events.jsonl` | Every event the console shows: phases, policy decisions, subagent scans, posture changes, web calls |
| `notifications.jsonl` | The notification screen's records |
| `metrics.jsonl` | Per-task routing decisions, token usage and egress records |
| `server.log` | The boot banner, including the egress guard's self-test |

**This is not live data.** The real `logs/` folder is gitignored: it records
what people type into the router, so it never goes into git history. Running
`./run_demo.sh` writes there, never here.

The sample covers demo sessions from 2026-08-16 to 2026-11-23 against the
seeded `demo/alpha-ip` corpus. It was reviewed before it was committed: it
contains no credentials, no personal paths and no real proprietary code.
Do not add new sessions here without the same review.

## Starting from the sample

```bash
./run_demo.sh --with-sample-logs
```

copies these `.jsonl` files into `logs/` before the router starts, and real
activity appends below them. A file is copied only if it is missing or empty,
so sample records are never mixed in ahead of real ones. Without the option,
`logs/` starts empty.

Each sample file ends with one marker record:

```json
{"kind": "sample-end", "marker": "--sample-logfile--ends-here----", "note": "..."}
```

Everything above it is sample data; everything below it happened on your
machine. Delete the lines above it, or the whole file, to start clean. The
marker is a JSON record rather than a bare text line so that tools reading the
file line by line keep working. To read only your own records:

```bash
sed '1,/--sample-logfile--ends-here----/d' logs/events.jsonl
```

(That prints everything after the marker. Use it only on a file that has one:
without a marker, `sed` would print nothing.)

`server.log` has no marker: `run_demo.sh` rewrites it on every start.
