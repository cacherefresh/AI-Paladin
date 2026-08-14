/*
 * AI-Paladin — VS Code status surface.
 *
 * This extension is a CLIENT. It reads GET /api/posture and renders the result;
 * it decides nothing and it changes nothing. That is deliberate, and it is a
 * security property rather than a missing feature:
 *
 *   The egress guard lives in the router's OS process. Every piece of logic
 *   moved out here is logic outside the perimeter, so the thinnest possible
 *   client keeps the largest possible share of the system inside it.
 *
 * The posture is therefore read-only from the editor. To arm or lift the
 * perimeter, use the console (or defaults.lock_mode in router/policy.yaml).
 *
 * Honest scope: the webview panel is a renderer inside VS Code's process tree.
 * It speaks only to loopback, but the router's guard has no visibility into it,
 * and VS Code itself is not inside the perimeter. See docs/ROADMAP.md section 5.
 */

const vscode = require("vscode");

const OFFLINE_POLL_MS = 10000;   // back off when the router is down
const REQUEST_TIMEOUT_MS = 1500; // loopback; if it is slow, it is wedged

let statusItem = null;
let panel = null;
let timer = null;
let disposed = false;

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

function cfg() {
  return vscode.workspace.getConfiguration("aiPaladin");
}

function endpoint() {
  const raw = cfg().get("endpoint") || "http://127.0.0.1:8722";
  return String(raw).replace(/\/+$/, "");
}

function onlinePollMs() {
  return Math.max(1, Number(cfg().get("pollSeconds") || 2)) * 1000;
}

// ---------------------------------------------------------------------------
// Posture polling
// ---------------------------------------------------------------------------

async function readPosture() {
  const res = await fetch(endpoint() + "/api/posture", {
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error("router returned HTTP " + res.status);
  return res.json();
}

function schedule(ms) {
  if (disposed) return;
  if (timer) clearTimeout(timer);
  timer = setTimeout(tick, ms);
}

async function tick() {
  let state = null;
  try {
    state = await readPosture();
  } catch (err) {
    state = null;
  }
  render(state);
  schedule(state ? onlinePollMs() : OFFLINE_POLL_MS);
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

function md(lines) {
  const t = new vscode.MarkdownString(lines.join("\n\n"));
  t.isTrusted = false;
  return t;
}

function render(state) {
  if (!statusItem) return;

  if (!state) {
    if (!cfg().get("showWhenOffline")) return statusItem.hide();
    statusItem.text = "$(circle-slash) AI-Paladin";
    statusItem.backgroundColor = undefined;
    statusItem.color = new vscode.ThemeColor("descriptionForeground");
    statusItem.tooltip = md([
      "**AI-Paladin — router not reachable**",
      "No posture is being enforced from this editor's point of view, because"
      + " there is nothing answering at `" + endpoint() + "`.",
      "Start it with `./run_demo.sh` in `ai-org-router/`.",
    ]);
    return statusItem.show();
  }

  const guard = state.guard || {};
  const scope = guard.scope || "loopback only";
  const blocks = Number(guard.blocks || 0);
  const mode = state.mode || "unknown";

  const detail = [];
  detail.push("Scope: `" + scope + "`");
  detail.push(
    guard.verified
      ? "Guard verified by self-test at boot."
      : "**Guard NOT verified — the sovereign posture is unavailable.**"
      + " The router refuses to enter a posture it could not prove it enforces."
  );
  if (blocks) {
    detail.push(
      blocks + " outbound attempt" + (blocks === 1 ? "" : "s") + " refused."
    );
  }
  if (state.lock_mode) {
    detail.push("Pinned to `" + state.lock_mode + "` by `defaults.lock_mode`.");
  }
  detail.push(
    "_Covers the router process only — this editor is not inside the guard._"
  );

  if (state.sealed) {
    statusItem.text = "$(shield) AI-Paladin: SEALED";
    statusItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
    statusItem.color = undefined;
    statusItem.tooltip = md(
      ["**Perimeter sealed** — posture `" + mode + "`",
       "Every destination that is not this machine is refused at the socket,"
       + " DNS included. BIG-AI is not declined; it is unreachable."]
        .concat(detail)
    );
  } else if (guard.verified === false) {
    statusItem.text = "$(warning) AI-Paladin: guard unverified";
    statusItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground"
    );
    statusItem.color = undefined;
    statusItem.tooltip = md(
      ["**Egress guard failed its self-test**"].concat(detail)
    );
  } else {
    statusItem.text = "$(shield) AI-Paladin: " + mode;
    statusItem.backgroundColor = undefined;
    statusItem.color = undefined;
    statusItem.tooltip = md(
      ["**Posture `" + mode + "`** — egress is available",
       "Protected IP is still pinned on-prem by the rules engine in every"
       + " posture; that invariant does not depend on this one."]
        .concat(detail)
    );
  }
  statusItem.show();
}

// ---------------------------------------------------------------------------
// Console panel
// ---------------------------------------------------------------------------

function consoleHtml(url) {
  let origin;
  try {
    origin = new URL(url).origin;
  } catch (err) {
    origin = url;
  }
  const csp = [
    "default-src 'none'",
    "style-src 'unsafe-inline'",
    "script-src 'unsafe-inline'",
    "frame-src " + origin,
  ].join("; ");

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<style>
  html,body{height:100%;margin:0;padding:0;
    background:var(--vscode-editor-background);
    color:var(--vscode-foreground);
    font-family:var(--vscode-font-family);font-size:var(--vscode-font-size)}
  body{display:flex;flex-direction:column}
  .bar{flex:none;display:flex;align-items:center;gap:10px;
    padding:6px 10px;border-bottom:1px solid var(--vscode-panel-border);
    font-size:12px}
  .bar .u{font-family:var(--vscode-editor-font-family);opacity:.75}
  .bar .sp{margin-left:auto}
  button{font:inherit;padding:3px 10px;border:0;border-radius:3px;cursor:pointer;
    background:var(--vscode-button-background);
    color:var(--vscode-button-foreground)}
  button:hover{background:var(--vscode-button-hoverBackground)}
  iframe{flex:1 1 auto;width:100%;border:0;background:#0b1219}
  .fallback{padding:18px 20px;max-width:60ch;line-height:1.55}
  .fallback code{font-family:var(--vscode-editor-font-family)}
</style>
</head>
<body>
  <div class="bar">
    <span class="u">${origin}</span>
    <span class="sp"></span>
    <button id="ext">Open in browser</button>
  </div>
  <iframe id="f" src="${url}" title="AI-Paladin console"></iframe>
  <div class="fallback" id="fb" style="display:none">
    <p><strong>The console did not load in this panel.</strong></p>
    <p>VS Code webviews apply a strict content policy, and embedding a local
    HTTP origin does not work in every configuration. This is a display
    limitation only &mdash; the router itself is unaffected, and its posture is
    still shown in the status bar.</p>
    <p>Use <em>Open in browser</em> above, or go to <code>${url}</code>.</p>
  </div>
<script>
  const vs = acquireVsCodeApi();
  document.getElementById("ext").addEventListener("click", function(){
    vs.postMessage({ type: "openExternal" });
  });
  // If the frame has not painted shortly after load, surface the escape hatch
  // rather than leaving a blank panel with no explanation.
  var loaded = false;
  var f = document.getElementById("f");
  f.addEventListener("load", function(){ loaded = true; });
  setTimeout(function(){
    if (!loaded) {
      f.style.display = "none";
      document.getElementById("fb").style.display = "block";
    }
  }, 4000);
</script>
</body>
</html>`;
}

function openConsole() {
  const url = endpoint();
  if (panel) {
    panel.reveal(vscode.ViewColumn.Beside);
    return;
  }
  panel = vscode.window.createWebviewPanel(
    "aiPaladin.console",
    "AI-Paladin",
    vscode.ViewColumn.Beside,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  panel.webview.html = consoleHtml(url);
  panel.webview.onDidReceiveMessage(function (msg) {
    if (msg && msg.type === "openExternal") openInBrowser();
  });
  panel.onDidDispose(function () {
    panel = null;
  });
}

function openInBrowser() {
  vscode.env.openExternal(vscode.Uri.parse(endpoint()));
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

function activate(context) {
  disposed = false;

  statusItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusItem.command = "aiPaladin.openConsole";
  statusItem.name = "AI-Paladin";
  context.subscriptions.push(statusItem);

  context.subscriptions.push(
    vscode.commands.registerCommand("aiPaladin.openConsole", openConsole),
    vscode.commands.registerCommand("aiPaladin.openInBrowser", openInBrowser),
    vscode.workspace.onDidChangeConfiguration(function (e) {
      if (e.affectsConfiguration("aiPaladin")) schedule(0);
    }),
    { dispose: function () {
        disposed = true;
        if (timer) clearTimeout(timer);
        timer = null;
      } }
  );

  tick();
}

function deactivate() {
  disposed = true;
  if (timer) clearTimeout(timer);
  timer = null;
}

module.exports = { activate, deactivate };
