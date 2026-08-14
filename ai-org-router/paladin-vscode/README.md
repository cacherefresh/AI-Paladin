# paladin-vscode

Shows the AI-Paladin router's egress posture in the VS Code status bar, and
opens its console in a panel.

```
 🛡 AI-Paladin: SEALED        ← perimeter armed, loopback only
 🛡 AI-Paladin: slow          ← egress available
 ⚠ AI-Paladin: guard unverified
 ⊘ AI-Paladin                 ← router not running
```

Click it to open the console.

## It is read-only, on purpose

This extension **cannot change the posture.** There is no "seal" command and no
"lift" command. That is a design decision, not a gap.

The egress guard lives inside the router's OS process, which is the only
process that talks to a model. Every piece of logic moved out of that process
is logic outside the perimeter — so the thinnest possible client keeps the
largest possible share of the system inside it. This extension reads
`GET /api/posture` and renders the answer. It decides nothing.

To change the posture, use the console, or pin the node by setting
`defaults.lock_mode` in `router/policy.yaml` — which the extension will show as
*pinned* in its tooltip.

## What the guard does and does not cover

Stated here because it is easy to assume otherwise once the shield is sitting
in your editor's status bar:

| | Inside the egress guard? |
|---|---|
| The router process (`python3 -m server.app`) | **Yes.** This is the guarded process, and it is the only one that talks to a model. |
| This extension's webview panel | **No.** It is a renderer in VS Code's process tree. It speaks only to loopback, but the router's guard has no visibility into it. |
| VS Code itself | **No.** Telemetry, settings sync, the extension gallery, `git push`. |
| The Ollama daemon | **No.** A separate process that can pull models from the internet. |

A green shield in the status bar means *the router cannot reach anything but
this machine.* It does not mean the machine is sealed. For that you want a host
firewall or a network namespace with no default route — see
[`docs/ROADMAP.md` §5](../docs/ROADMAP.md).

If you are running a demo where "nothing left the machine" is the claim, harden
VS Code as well — the table in
[`docs/DEMO_SOVEREIGN_MIXXX.md`](../docs/DEMO_SOVEREIGN_MIXXX.md) lists the
settings.

## Install

No build step. From this directory:

```bash
npx @vscode/vsce package        # produces ai-paladin-0.1.0.vsix
code --install-extension ai-paladin-0.1.0.vsix
```

Or press <kbd>F5</kbd> in this folder to launch an Extension Development Host
for iteration.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `aiPaladin.endpoint` | `http://127.0.0.1:8722` | Base URL of the router. It binds to loopback only; a remote host will not work. |
| `aiPaladin.pollSeconds` | `2` | Posture read interval while the router is up. Backs off to 10 s while it is down. |
| `aiPaladin.showWhenOffline` | `true` | Keep the item visible when the router is not running. |

## Commands

| Command | Notes |
|---|---|
| `AI-Paladin: Open Console` | Opens the console in a webview panel beside the editor. |
| `AI-Paladin: Open Console in Browser` | Opens it in the system browser instead. |

The webview embeds the console at `aiPaladin.endpoint`. VS Code applies a
strict content policy to webviews and embedding a local HTTP origin does not
work in every configuration — if the panel does not paint, it falls back to a
message and an **Open in browser** button after a few seconds. That is a
display limitation only; the router and its guard are unaffected, and the
status bar keeps working either way.

## Future, well past MVP

Splitting into `paladin-core` / `paladin-client` / `paladin-standalone` /
`paladin-vscode` packages is the right eventual shape for shipping, and is
deliberately deferred — it adds a build step and changes nothing about where
the perimeter sits. See [`docs/ROADMAP.md` §5](../docs/ROADMAP.md), *Client
shape*.
