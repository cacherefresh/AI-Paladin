# AI-Paladin
Security Focused, Alpha protector and token reducer by using a distributed mesh grid of onprem a.i. - the reason gates are hooks and YAML rather than prompt instructions:prompt is a suggestion; a hook is a wall. A manipulated or misbehaving agent can ignore "please don't delete files";it cannot ignore PreToolUse script exit 2. security-focused repo

## Run it

```bash
cd ai-org-router
./run_demo.sh            # start (also: stop, restart) -> http://localhost:8722
./run_demo.sh --with-sample-logs   # ...and seed an empty logs/ from logs.example/
./stop_demo.sh           # stop router, unload models, stop ollama
./stop_demo.sh --keep-ollama   # ...but leave ollama running
./stop_demo.sh --router-only   # stop the router only
```

Needs Python 3 with PyYAML and [Ollama](https://ollama.com) serving on
`localhost:11434`. The server binds to `127.0.0.1` only and has **no
authentication** - it is a single-user demo, not a shared service.

## Settings

Every setting below is a file or a dashboard control. Files under `router/`
and `security/policies/` are **enforcement, not documentation** - edit them to
change policy, never to make a test pass or a demo read better.

### Environment

| Variable | Default | What it does |
|---|---|---|
| `PALADIN_PORT` | `8722` | Port the router listens on |
| `PALADIN_PYTHON` | first `python3` that can import PyYAML | Interpreter `run_demo.sh` uses |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint for `bench/bench.py` only; the router reads `nodes.onprem.endpoint` in `router/policy.yaml` |

### The invariant - not a setting

`router/keywords.yaml` lists protected terms and protected paths. A prompt, or
a file it would carry, that matches one runs **on-prem, in every posture,
before any socket opens**. No dashboard control, mode or model can override
it. Edit the file to change *what* is protected, not *whether*.

### Routing posture (dashboard: the four mode cards)

Decides where work that does **not** match the keyword gate goes.

| Posture | Non-matching work goes to | Before anything leaves |
|---|---|---|
| `sovereign` | on-prem - nowhere else is reachable | Nothing can leave: the egress guard refuses every non-loopback connection, DNS included |
| `slow` (default) | on-prem; escalation is an opt-in | A human confirms |
| `fast` | BIG-AI | A human confirms |
| `superfast` | BIG-AI, minimal payload | A human confirms, after a disclosure window itemises every byte |

In `router/policy.yaml`: `defaults.mode` sets the starting posture, and
`defaults.lock_mode: sovereign` (or any mode id) pins it - the mode bar greys
out and the API refuses every other posture. Every posture change is
audited; lifting `sovereign` is logged as critical. The egress guard is
**process-level**: it covers every socket the router opens, not the rest of
the machine. It is not a host firewall and not an air gap.

### On-prem model (dashboard: model picker)

| Where | Setting |
|---|---|
| `models/catalog.yaml` | The models offered, `default`, `fallback`, and `license_allowlist` (Apache-2.0, MIT). A model whose licence is not on the list is shown but cannot be selected. |
| `config/local_models.yaml` | This machine's selection, written by the dashboard. Gitignored. |

The server never downloads a model - pulling is egress. A missing model is
shown with the `ollama pull` command for a person to run.

### Internet access for the on-prem model (dashboard: three buttons)

| Setting | In plain terms | HTTP methods (defaults) |
|---|---|---|
| `no-external-network-io` | **LLM** - what it was trained on plus your files. No web. | none - all 41 blocked |
| `READ-ONLY` (default) | **RAG** - looks things up on the web; cannot write to it | GET, QUERY |
| `READ/WRITE` | **Bot** - a RAG that can also act: forms, write APIs, sign-in | GET, QUERY, POST, PUT, PATCH, DELETE |

Most restrictive wins: `sovereign` forces no-external-network-io; a task that
matched the keyword gate is lowered from read/write to read-only; and
`internet_access.lock` pins the setting. Read/write needs a confirmation to
switch on. The setting is **not persisted** - every restart begins at
`internet_access.default`. Everything the model sends out (a search, a URL, a
form field, a header) passes the same keyword gate as a prompt.

### HTTP method switches (dashboard: chips under the internet buttons)

Every method in the IANA HTTP Method Registry, plus PURGE, is classed in
`ai_paladin/nodes/web_tools.py`. Anything else is refused.

| Class | Methods |
|---|---|
| read (7) | GET, HEAD, OPTIONS, QUERY, PROPFIND, REPORT, SEARCH |
| write (31) | POST, PUT, PATCH, DELETE, the 24 WebDAV writes (COPY, MOVE, LOCK, MKCOL, PROPPATCH, ...), LINK, UNLINK, PURGE |
| never (4) | TRACE, CONNECT, PRI, `*` - cannot be enabled anywhere |

Three switches widen or narrow a setting, from
`internet_access.method_toggles`:

| Switch | Adds | Default | In read-only |
|---|---|---|---|
| **Header checks** | HEAD, OPTIONS - check a URL without downloading it | off | applies |
| **WebDAV** | file shares, calendars, versioning: PROPFIND, REPORT, SEARCH + 24 writes | off | reads only |
| **DELETE** | DELETE - switch off for a bot that can create but not destroy | on | no effect |

A switch can never give read-only a write. Switching on WebDAV or DELETE
needs a confirmation, every switch change is audited, switches reset to their
defaults on restart, and `internet_access.lock` holds them there. LINK,
UNLINK and PURGE have no switch: list one under read/write's `methods` in
`router/policy.yaml` if you need it. The dashboard shows exactly what is
allowed; hover "BLOCKED" for the full list. Detail:
[ai-org-router/ai_paladin/nodes/README.md](ai-org-router/ai_paladin/nodes/README.md).

### Web limits (`internet_access.limits`)

| Limit | Default | |
|---|---|---|
| `max_calls_per_task` | 6 | Web requests one task may make |
| `max_response_bytes` | 600000 | Bytes read from one response |
| `max_result_chars` | 5000 | Text handed back to the model per call |
| `max_query_chars` | 300 | Length of a search query |
| `max_body_chars` | 4000 | Length of a request body the model writes |
| `timeout_s` | 15 | Per-request timeout |

`internet_access.search.endpoint` sets the search engine (DuckDuckGo Lite by
default). Web tools reach public addresses on ports 80 and 443 only - never
loopback, the LAN or link-local.

### Web sign-in accounts (`config/web_accounts.yaml`, gitignored)

```yaml
accounts:
  github:
    domains: [github.com]
    fields: {login: "...", password: "..."}
```

Read/write only. The model names an account; it never sees the field values,
and an account is only ever sent to a host on its own `domains` list.

### BIG-AI (`nodes.bigai` in `router/policy.yaml`)

`backend: simulated` today - the escalation leg streams a stub, badged
`SIMULATED` on screen, with latency labelled *(modelled)*. The real Claude
adapter is not built yet: `ai_paladin/bigai/simulated.py:call_claude` is the seam, and
it will need `ANTHROPIC_API_KEY`.

### Token pricing (`pricing` in `router/policy.yaml`)

`price_per_mtok_in` and `price_per_mtok_out` are deliberately `null`. Set your
own contracted rates and the session ledger shows spend; leave them null and
it reports tokens only, never a guessed dollar figure.

### Subagents (`agents/roster.yaml`)

Each subagent - `sentry` (semantic gate), `clerk` (triage), `engineer`
(on-prem execution), `consultant` (BIG-AI escalation) - has an `enabled` flag
and a model; the local ones also have a `budget_ms`. `sentry`'s `threshold`
sets how close a paraphrase must be to a protected term to count as a match;
if it is unavailable the router falls back to the exact keyword gate alone,
never weaker. `typo_gate` (`enabled`, `min_similarity: 0.85`) catches
misspelled protected terms such as "pricng engnie" - arithmetic, no model.

## Dedication

I, ℝobert l ℂoffman aka DJ YuVi (UV) UltraViolet aka ℂacheℝefresh am dedicating this to **Jensen Huang** of NVIDIA, who remember's his rooots as do I, stood by (We The People)gamers and the free and open source society FOSS such as when the cards
were scarce, ensuring gamers got some when crypto bankers wanted them. I'm TEAM AMD / ATI for life, but you connected me with my fellow gamer/hackers The full dedication and the ℂacheℝefresh statement of principles. Know that I am broke losing my house as AI took my job among other things. But SECURITY should never be gate kept for those with money. I do accept job offers and donations tho haha.

You bought hugging face and supported open weight models. it's like the digital version of the SECOND AMENDMENT in case of a tyrannical Big Tech. 
I'll join you. From the bottom and the underground... See you at the top.

more at the top of [LICENSE](LICENSE). AI-Paladin is not affiliated with or
endorsed by NVIDIA. (╯°□°)╯︵ ┻━┻ ..............┬─┬ノ( º _ ºノ) 

We are ℂomplex people but have all ℝeal lives... Peace On Earth 🕊🐦‍⬛ 

## License

Open source under a **modified Apache License 2.0**. The only modification is
a non-binding dedication and statement of principles added as a preamble. The
license terms themselves are the Apache License 2.0, word for word. See
[LICENSE](LICENSE) and [NOTICE](NOTICE).
