# hooks/

The Claude Code **PreToolUse** hook: `security/policies/` and
`security/monitors/` enforced on a coding agent's tool calls.

- `pre_tool_use.py` - runs `ai_paladin/hook.py`. Point Claude Code at this
  file, or, with AI-Paladin installed, at the `ai-paladin-hook` command.

**It does not need the AI-Paladin router to be running.** Claude Code starts
the hook fresh for every tool call, and it reads the policy files straight
from disk. The router's own enforcement (allowlist, credential files,
fence-probing on web tools) is separate and only applies while the router
runs.

A prompt is a suggestion; a hook is a guardrail. Claude Code runs the hook
before every matching tool call. Exit 2 refuses the call and shows the agent
why, and the agent cannot talk its way past a refusal. **The hook is a
hardened guardrail, not a security boundary.** It reads what a tool call
would touch - shell commands unwrapped from `sh -c` / `eval` / `$(...)`,
paths resolved through quoting, variables, `cd`, `../` and symlinks, the
files a command or an agent-written script writes - but it runs in the same
user space as the agent and reads code rather than running it, so a
determined agent can still route around it (see Limits). The 11 bypasses
once pinned as expected failures in `tests/test_hook_bypasses.py` are
closed and now pass as regression tests. Making it a true boundary is a
roadmap goal (`docs/ROADMAP.md`, section 9).

## What it enforces

| Rule | File | What happens |
|---|---|---|
| Blocked commands (`rm -rf /`, `curl … \| bash`, `nc -l`, …) | `commands.yaml` `block` | Bash call refused, including when nested in `sh -c`, `bash -c`, `eval`, `$(...)`, backticks or a here-doc fed to a shell |
| Write scope | `commands.yaml` `write_scope` | Write / Edit / MultiEdit / NotebookEdit (and MCP write tools) outside the project folder or `/tmp/agent-<session>`, or into `/etc`, `/usr`, `~/.ssh`, `~/.aws`, backups, `.git/objects`, refused. Files written by Bash (`>`, `tee`, `cp`, `mv`, `rm`, `sed -i`, `dd of=`, …) and by interpreter code or agent-written scripts (`python3 -c`, `python3 x.py`, `./x.sh`, …) are checked against `deny`, not `allow`. Paths are resolved first: quoting, `~`, `$VAR`, globs, `cd`, `../`, symlinks |
| Package installs | `packages.yaml` | pip / npm / pnpm / yarn / cargo / poetry installs refused unless the package is on the allowlist with a pinned, matching version; URLs, paths, `-e` and `-r` refused. Nested shells and `subprocess` / `os.system` calls in scripts are checked too |
| credential-path-access | `behavioral_rules.yaml` | Read / Grep / Glob / Write / Edit / MCP tools / `file:` WebFetch on `.ssh`, `.aws`, `.env`, `.env.*`, and Bash commands or interpreter code naming them (after quote removal and path resolution), refused |
| mass-file-touch | `behavioral_rules.yaml` | More than 200 file-tool writes in 60 s: further writes refused |
| fence-probing | `behavioral_rules.yaml` | More than 3 refusals in one session: **every** tool call refused until a person releases it |
| hook-tamper | `behavioral_rules.yaml` | An agent switching off or editing the guard: Claude Code settings files, AI-Paladin's config and log folders (configured and default locations), AI-Paladin's policy files (`router/keywords.yaml`, `router/policy.yaml`, `config/keywords.yaml`, `security/policies/`, `security/monitors/` in any AI-Paladin tree), by any route the hook inspects; `ai-paladin-hook --release/--install/--uninstall`, `ai-paladin uninstall`, `pip uninstall ai-paladin` |

Tools covered: Bash, Write, Edit, MultiEdit, NotebookEdit, Read, Grep,
Glob, WebFetch, WebSearch, Task / Agent and every MCP tool (`mcp__.*`).
WebSearch and Task / Agent have no path to check; they are logged, count
toward fence-probing and are refused while a session is paused. **An install
made before this list grew keeps its old, shorter matcher: run
`ai-paladin-hook --install` again to update it.**

Every decision, allowed or refused, is appended to `hooks.jsonl` in the log
folder (`~/.local/state/ai-paladin/logs/` by default). The hook **fails
closed**: if it errors, or gets input it cannot read, it refuses the call.

## Turning it on and off

Only a person does this. The hook refuses an agent that tries to run these
commands, edit Claude Code's settings files, edit AI-Paladin's config or log
folders, or `pip uninstall ai-paladin` (rule `hook-tamper`).

Run these **in the project you want guarded**: without `--user`, they act on
the `.claude/` folder of the current directory.

```bash
ai-paladin-hook --install            # this project only (.claude/settings.local.json)
ai-paladin-hook --install --user     # every project (~/.claude/settings.json)
ai-paladin-hook --status             # every place it is installed; paused sessions
ai-paladin-hook --uninstall          # remove it (add --user for the global one)
ai-paladin-hook --uninstall --all    # remove it from every place it was installed
```

Without `pip install -e .`, use the file by its full path, still from your
project: `python3 /path/to/AI-Paladin/ai-paladin/hooks/pre_tool_use.py --install`.

**If AI-Paladin was removed first** and Claude Code now refuses everything,
Claude Code cannot fix itself - use an ordinary terminal in the guarded
project and run the same command with `--uninstall` (add `--user` if you
installed it for every project). If the AI-Paladin folder is gone too, delete
the `pre_tool_use.py` entry under `hooks.PreToolUse` in the settings file by
hand.

`--install` keeps everything else in the settings file, replaces any older
AI-Paladin entry rather than adding a second one, and saves the previous
file as `settings*.json.bak`. It refuses to touch a settings file it cannot
read. Claude Code picks the change up in new sessions.

**Remove AI-Paladin with `ai-paladin uninstall`, not a plain `pip
uninstall`.** `--install` records every settings file it writes to; `ai-paladin
uninstall` removes the hook from all of them, then the package, and ends with
a banner confirming both. pip cannot run anything at uninstall time, so it
cannot do this for you.

Claude Code blocks a call only when a hook exits with code 2; any other
failure is shown as a warning and **the call goes ahead**. So the line
`--install` writes is built to refuse whenever the hook cannot run - python3
missing, the folder moved, AI-Paladin removed - rather than silently letting
everything through:

| Hook result | Claude Code |
|---|---|
| allowed (exit 0) | runs the call |
| refused (exit 2) | refuses it, with the rule and reason |
| could not run at all | refuses it, **and says how to recover**: which settings file to edit, or the `--uninstall` command to run |

The cost: if AI-Paladin is removed while the entry is still there, Claude
Code refuses every tool call until the entry is removed - but it tells you
so, and where, instead of failing silently.

The hook reads the same settings folder as the router, so a `commands.yaml`,
`packages.yaml` or `behavioral_rules.yaml` in `~/.config/ai-paladin/`
replaces the shipped one.

## Settings: `hook.yaml`

The hook's own switches live in `hook.yaml` in your settings folder
(`~/.config/ai-paladin/hook.yaml`, or `$AI_PALADIN_CONFIG_DIR/hook.yaml`).
No file means every default. It is a user setting, not a policy file: the
shipped `security/policies/` files are unchanged, and this file sits in the
config folder that rule `hook-tamper` keeps agents out of, so only a person
can change it. An unknown key or a value that is not `true` / `false` makes
the hook refuse every call (fail closed) until it is fixed, so a misspelt
setting is never silently ignored. `ai-paladin-hook --status` shows the
current values.

| Setting | Default | What it does |
|---|---|---|
| `shell_writes_enforce_allow` | `false` | Files written by Bash commands and interpreter code are always checked against `write_scope.deny` and the protected files. With `true`, they must also be inside `write_scope.allow` (the project folder and `/tmp/agent-<session>`): a shell write anywhere else is refused (`out-of-scope-path`). Off by default because ordinary shell work writes outside the project (`rm -rf /tmp/build`, `mkdir -p ~/scratch`). `/dev/null`, `/dev/stderr` and `>&2` are never files. |
| `scripts_may_read_env_files` | `false` | A script **file** the agent runs (`python3 app.py`, `./run.sh`, `source x`) that names a `.env` / `.env.*` file - e.g. `load_dotenv(".env")` - is refused by default (credential-path-access). With `true`, such a script may name `.env` files. Still refused either way: `.ssh` / `.aws`, a script that writes a `.env`, inline code (`python3 -c`, here-docs), typed commands (`cat .env`, `source .env`) and the Read / Write tools. |

```yaml
# ~/.config/ai-paladin/hook.yaml
shell_writes_enforce_allow: true
scripts_may_read_env_files: false
```

## After a pause

```bash
ai-paladin-hook --status              # sessions, refusal counts, PAUSED
ai-paladin-hook --release SESSION_ID  # a person lifts the pause
```

(Without installing: `python3 /path/to/AI-Paladin/ai-paladin/hooks/pre_tool_use.py --status`.)

## Limits

- **A hardened guardrail, not a boundary.** Decision (Rob, 2026-11-28): the
  hook is a guardrail; the 11 known bypasses were closed before
  distribution, and the true boundary is OS-level (`docs/ROADMAP.md`,
  section 9).
- **It reads, it does not run.** Shell commands and scripts are parsed, not
  executed. A path or command decided only at run time - a variable set by
  another program, an alias or function, a string decoded from base64, a
  path assembled in a loop, a module a script imports, a program that
  writes files on its own terms (`git checkout`, `make`) - is not seen.
  Run agents in a sandbox as well (`security/sandbox.md`).
- By default, Bash and script writes are checked against
  `write_scope.deny` and the protected files, not against
  `write_scope.allow` (ordinary shell work such as `rm -rf /tmp/build`
  writes outside the project); set `shell_writes_enforce_allow: true` in
  `hook.yaml` to enforce the allow list too. Bash renames are
  not counted as writes for mass-file-touch.
- It cannot kill an agent. "kill_agent" rules are carried out by refusing
  the call.
- Package checksums (`require_checksum`) and the approval queue in
  `packages.yaml` are not enforced yet.
- It does not gate Claude Code's own network use: WebFetch and WebSearch
  reach the hook (logged, paused with the session, `file:` URLs checked),
  but no domain allowlist is applied to them.
- `hook-tamper` matches what a command names or resolves to. It also
  refuses harmless commands that merely mention those files
  (`cat .claude/settings.json`), and a program that changes them with a
  path computed at run time is not caught.
