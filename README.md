# AI-Paladin - An AI-Org-Router

> The project folder was formerly `ai-org-router/`; it is now `ai-paladin/`. Older
> links, notes and clones that mention `ai-org-router/` mean the same code.

Security Focused, Alpha protector and token reducer by using a distributed mesh grid of onprem a.i. - the reason gates are hooks and YAML rather than prompt instructions:a prompt is a suggestion; a hook is a guardrail. A manipulated or misbehaving agent can ignore "please don't delete files"; it cannot ignore a PreToolUse script exit 2 - the hook is a hardened guardrail: it resolves what a tool call or shell command would actually touch, but it reads commands rather than running them and shares the agent's user space, so it is not a security boundary a determined agent cannot route around ([limits](ai-paladin/hooks/README.md#limits); making it a real boundary is a [roadmap goal](ai-paladin/docs/ROADMAP.md)). security-focused repo

## Run it

```bash
cd ai-paladin
./run_demo.sh            # start (also: stop, restart) -> http://localhost:8722
./run_demo.sh --with-sample-logs   # ...and seed an empty logs/ from logs.example/
./stop_demo.sh           # stop router, unload models, stop ollama
./stop_demo.sh --keep-ollama   # ...but leave ollama running
./stop_demo.sh --router-only   # stop the router only
```

Needs Python 3 with PyYAML and [Ollama](https://ollama.com) serving on
`localhost:11434`. The server binds to `127.0.0.1` only and has **no
authentication** - it is a single-user demo, not a shared service.

The demo keeps everything in the repo: settings in `ai-paladin/config/`
(including the demo's keyword overlay), logs in `ai-paladin/logs/`.

### The `ai-paladin` command

```bash
pip install -e .            # from the repo root: puts `ai-paladin` on your PATH
ai-paladin                  # start, with your own settings and logs (below)
ai-paladin --demo           # start the way run_demo.sh does
ai-paladin --where          # show which files are in force, and exit
python3 -m ai_paladin       # the same, without installing (from ai-paladin/)
```

Only an editable install (`pip install -e`) works today; a packaged release
is planned in [DISTRIBUTION/](DISTRIBUTION/).

## Settings

The full configuration manual, with every default and how to change it, is
[USER_CONFIG/USER_MANUAL/USER_CONFIG_DECK.pdf](USER_CONFIG/USER_MANUAL/USER_CONFIG_DECK.pdf).

Every setting below is a file or a dashboard control. Files under `router/`
are **enforcement, not documentation** - edit them to change policy, never to
make a test pass or a demo read better.

### Where settings live

| | Default | Demo (`run_demo.sh`, `--demo`) | Override |
|---|---|---|---|
| Shipped defaults (read-only) | `ai-paladin/router/`, `agents/`, `models/` | same | - |
| Your settings | `~/.config/ai-paladin/` | `ai-paladin/config/` | `AI_PALADIN_CONFIG_DIR` |
| Audit logs | `~/.local/state/ai-paladin/logs/` | `ai-paladin/logs/` | `AI_PALADIN_LOG_DIR` |

Never edit the shipped files to configure your own install - put your
version in your settings folder:

| File in your settings folder | How it combines with the shipped default |
|---|---|
| `keywords.yaml` | **Overlay.** Lists changes: `groups`, `add_terms`, `remove_terms`, `remove_groups`, `add_paths`, `remove_paths`. Leaving a term out removes nothing; only naming it under `remove_*` does. Updated defaults still reach you. |
| `policy.yaml`, `roster.yaml`, `catalog.yaml` | **Replaces** the shipped file whole, if present. |
| `local_models.yaml` | Written by the dashboard's model picker. |
| `web_accounts.yaml` | Sign-in secrets. Yours to write; keep it `chmod 600`. |

Every boot prints each file in force, where it came from and its checksum.
Every protection a user overlay removes is printed as **WEAKENED** and
written to the audit log. A malformed overlay stops the router from starting
rather than running with rules you did not intend.

### Environment

| Variable | Default | What it does |
|---|---|---|
| `PALADIN_PORT` | `8722` | Port the router listens on |
| `PALADIN_PYTHON` | first `python3` that can import PyYAML | Interpreter `run_demo.sh` uses |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint for `bench/bench.py` only; the router reads `nodes.onprem.endpoint` in `router/policy.yaml` |

### The invariant - not a setting

`router/keywords.yaml` lists protected terms and protected paths, and your
`keywords.yaml` overlay adds to or removes from them. A prompt, or a file it
would carry, that matches one runs **on-prem, in every posture, before any
socket opens**. No dashboard control, mode or model can override it. The
files change *what* is protected, not *whether*.

The shipped defaults are deliberately small and generic: government
classification markings (classified, top secret, noforn, controlled
unclassified), credentials, customer data / PII, and internal
infrastructure. The demo's own terms (nightjar, pricing engine, unreleased
earnings, ...) live in the demo overlay, `ai-paladin/config/keywords.yaml`.

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
| `local_models.yaml` in your settings folder | This machine's selection, written by the dashboard. |

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
[ai-paladin/ai_paladin/nodes/README.md](ai-paladin/ai_paladin/nodes/README.md).

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

### Domain allowlist (`internet_access.allow_domains`)

| `allow_domains` | Which websites the on-prem model may reach |
|---|---|
| **empty `[]` - the default** | **Any public website** (ports 80/443). Nothing is restricted by domain. |
| a list, e.g. `[python.org, lite.duckduckgo.com]` | **Only** those domains and their subdomains (`python.org` also allows `docs.python.org`). Anything else is refused and logged as `unknown-egress`. |

If you set a list, include your search engine's host
(`lite.duckduckgo.com` by default), or web search stops working. Every other
web rule - the internet-access setting, HTTP methods, public addresses only,
the protected-term check, the per-task budget - applies either way.

Repeated refusals are also caught: when more than 3 web requests in one task
are refused (`fence-probing`), that task's web tools stop and a critical
notification asks a person to look. The model still finishes its answer,
without the web.

### Web sign-in accounts (`web_accounts.yaml` in your settings folder)

```yaml
accounts:
  github:
    domains: [github.com]
    fields: {login: "...", password: "..."}
```

Read/write only. The model names an account; it never sees the field values,
and an account is only ever sent to a host on its own `domains` list.

### Security policies (`security/policies/`, `security/monitors/`)

These rules are for a **coding agent** such as Claude Code: shell commands,
file writes, package installs. The router's own on-prem model cannot run
commands or write files, so most of them are enforced by the Claude Code
PreToolUse hook - **only once you install it**
([ai-paladin/hooks/README.md](ai-paladin/hooks/README.md)).

| File | Enforced by | What |
|---|---|---|
| `commands.yaml` | hook | Blocked shell commands; where file-writing tools may write |
| `packages.yaml` | hook | Package installs: allowlist, pinned versions, nothing from URLs or files. Checksums and the approval queue: **not yet** |
| `behavioral_rules.yaml` | hook and router | credential-path-access (router: credential files are never given to the on-prem model; hook: refused), fence-probing (both), unknown-egress (router, with an allowlist), mass-file-touch, out-of-scope-path and backup-tamper (hook). extension-rewrite-spread: **not yet** |

**Turning the hook on and off** is a person's job, and it does not depend on
the router running: `ai-paladin-hook --install` adds it to this project's
Claude Code settings (`--user` for every project), `--uninstall` removes it,
`--status` shows where it is. Stopping the router does **not** switch the
hook off - otherwise stopping the router would be the way past every rule.
Remove AI-Paladin with `ai-paladin uninstall`, which takes the hook out
everywhere first; a plain `pip uninstall` leaves it behind, and Claude Code
then refuses every tool call until the entry is removed.

Each rule in `behavioral_rules.yaml` says, on its own `enforced:` line,
exactly where and how it is enforced - or that it is not. The hook is a
tripwire, not a sandbox: it reads tool calls, not what a command does once
it runs.

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

## Uninstalling

```bash
ai-paladin uninstall
```

**Use this, not a plain `pip uninstall`.** It removes the Claude Code hook
from every project where it was installed - `--install` keeps a record of
each one - and only then uninstalls the package, ending with a banner that
confirms both. If any hook entry cannot be removed, it stops and uninstalls
nothing. (Installed with pipx? It runs `pipx uninstall` for you.)

pip itself cannot help here: it runs no code from a package while removing
it, so a plain `pip uninstall` can neither remove the hook nor warn you.

To turn the hook off but keep AI-Paladin: `ai-paladin-hook --uninstall --all`
(or `--uninstall` in one project).

Why the order matters: the hook is built to refuse a tool call whenever it
cannot run, so a broken install never lets an agent through unchecked. If
AI-Paladin is removed first, Claude Code refuses every tool call. It tells
you why and which settings file to fix; in an ordinary terminal, delete the
`pre_tool_use.py` entry under `hooks.PreToolUse` in that file, and new
sessions work normally.

Your settings (`~/.config/ai-paladin/`) and audit logs
(`~/.local/state/ai-paladin/`) are kept. Delete those folders yourself if
you want them gone.

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
