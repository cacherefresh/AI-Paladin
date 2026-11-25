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

A prompt is a suggestion; a hook is a wall. Claude Code runs the hook before
every matching tool call. Exit 2 refuses the call and shows the agent why;
the agent cannot talk its way past it.

## What it enforces

| Rule | File | What happens |
|---|---|---|
| Blocked commands (`rm -rf /`, `curl … \| bash`, `nc -l`, …) | `commands.yaml` `block` | Bash call refused |
| Write scope | `commands.yaml` `write_scope` | Write / Edit / MultiEdit / NotebookEdit outside the project folder or `/tmp/agent-<session>`, or into `/etc`, `/usr`, `~/.ssh`, `~/.aws`, backups, `.git/objects`, refused. Symlinks are resolved first |
| Package installs | `packages.yaml` | pip / npm / pnpm / yarn / cargo / poetry installs refused unless the package is on the allowlist with a pinned, matching version; URLs, paths, `-e` and `-r` refused |
| credential-path-access | `behavioral_rules.yaml` | Read / Grep / Glob / Write / Edit on `.ssh`, `.aws`, `.env`, `.env.*`, and Bash commands naming them, refused |
| mass-file-touch | `behavioral_rules.yaml` | More than 200 file-tool writes in 60 s: further writes refused |
| fence-probing | `behavioral_rules.yaml` | More than 3 refusals in one session: **every** tool call refused until a person releases it |
| hook-tamper | `behavioral_rules.yaml` | An agent switching off or editing the guard: Claude Code settings files, AI-Paladin's config and log folders, `ai-paladin-hook --release/--install/--uninstall`, `ai-paladin uninstall`, `pip uninstall ai-paladin` |

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
project: `python3 /path/to/AI-Paladin/ai-org-router/hooks/pre_tool_use.py --install`.

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

## After a pause

```bash
ai-paladin-hook --status              # sessions, refusal counts, PAUSED
ai-paladin-hook --release SESSION_ID  # a person lifts the pause
```

(Without installing: `python3 /path/to/AI-Paladin/ai-org-router/hooks/pre_tool_use.py --status`.)

## Limits

- **A tripwire, not a sandbox.** It reads tool calls, not what a shell
  command does once it runs. Variables, aliases, encodings and scripts can
  hide a command from a pattern. Run agents in a sandbox as well
  (`security/sandbox.md`).
- Bash commands that write files (`>`, `cp`, `mv`, `rm`) are not checked
  against the write scope, and Bash renames are not counted as writes.
- It cannot kill an agent. "kill_agent" rules are carried out by refusing
  the call.
- Package checksums (`require_checksum`) and the approval queue in
  `packages.yaml` are not enforced yet.
- It does not gate Claude Code's own network use (WebFetch, WebSearch).
- `hook-tamper` matches what a command names. It also refuses harmless
  commands that merely mention those files (`cat .claude/settings.json`),
  and a script that changes them without naming them is not caught.
