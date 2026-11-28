#!/usr/bin/env python3
"""
Wheel smoke test: build the wheel, install it into a clean virtual
environment, and run AI-Paladin from the installed copy only.

    python3 ai-paladin/tests/wheel_smoke.py          (from the repo root)

It proves what an editable install cannot: that the wheel carries the
shipped defaults (gate YAML, UI, demo corpus, hook wrapper) and every code
subpackage. Steps, each of which must pass:

  1. build the wheel with `pip wheel --no-deps` from a copy of the
     git-tracked files (so commit or `git add` new files first)
  2. every ai_paladin code subpackage in the source tree is in the wheel
  3. create a clean venv and pip install the wheel (PyYAML from the index)
  4. from a folder outside the repo: ai_paladin imports from the venv, and
     paths.BASE is the packaged ai_paladin/_shipped/
  5. `ai-paladin --where` lists every shipped file
  6. `ai-paladin --port N` boots, passes the egress self-test, serves the
     dashboard with its API token, and refuses an untokened POST
  7. `ai-paladin-hook` allows `ls` (exit 0) and refuses `rm -rf /` (exit 2)

No Ollama is needed; the router reports the on-prem model OFFLINE and runs.
Exit status 0 means every step passed.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROUTER = os.path.dirname(HERE)
REPO = os.path.dirname(ROUTER)


def step(msg):
    print("[wheel-smoke] " + msg, flush=True)


def run(cmd, **kw):
    kw.setdefault("check", True)
    return subprocess.run(cmd, **kw)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ai-paladin-wheel-")
    dist = os.path.join(tmp, "wheelhouse")

    step("1. building the wheel")
    # Build from a clean copy of the tracked files, so a stale build/ or
    # egg-info folder in the checkout cannot hide a packaging mistake, and
    # the checkout is left untouched.
    src = os.path.join(tmp, "src")
    os.makedirs(src)
    tracked = run(["git", "-C", REPO, "ls-files", "-z"], capture_output=True,
                  ).stdout.decode("utf-8").split("\0")
    for rel in filter(None, tracked):
        if os.path.isfile(os.path.join(REPO, rel)):
            os.makedirs(os.path.dirname(os.path.join(src, rel)), exist_ok=True)
            shutil.copy2(os.path.join(REPO, rel), os.path.join(src, rel))
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", dist,
         src])
    wheels = [f for f in os.listdir(dist) if f.endswith(".whl")]
    assert len(wheels) == 1, wheels
    whl = os.path.join(dist, wheels[0])

    step("2. checking the wheel's contents")
    names = set(zipfile.ZipFile(whl).namelist())
    src_pkgs = sorted(
        os.path.relpath(root, ROUTER).replace(os.sep, "/")
        for root, _dirs, files in os.walk(os.path.join(ROUTER, "ai_paladin"))
        if "__init__.py" in files and "__pycache__" not in root)
    missing = [p for p in src_pkgs if p + "/__init__.py" not in names]
    assert not missing, "code packages missing from the wheel " \
        "(add them to [tool.setuptools] packages): %s" % missing
    sys.path.insert(0, ROUTER)
    from ai_paladin import config_layers               # noqa: E402
    need = ["ai_paladin/_shipped/" + "/".join(rel)
            for rel in config_layers.SHIPPED_FILES.values()]
    need += ["ai_paladin/_shipped/ui/demo/index.html",
             "ai_paladin/_shipped/hooks/pre_tool_use.py"]
    absent = [n for n in need if n not in names]
    assert not absent, "shipped defaults missing from the wheel: %s" % absent
    assert not [n for n in names if ".egg-info/" in n or "/logs/" in n
                or n.endswith("local_models.yaml")
                or n.endswith("web_accounts.yaml")], "stray files in wheel"
    repo_only = ("AGENTS.md", "CLAUDE.md", "HANDOFF.md")
    leaked = [n for n in names
              if any(n == x or n.endswith("/" + x) for x in repo_only)]
    assert not leaked, "repo-only agent files must not ship in the wheel: %s" % leaked

    step("3. installing into a clean venv")
    venv = os.path.join(tmp, "venv")
    run([sys.executable, "-m", "venv", venv])
    vbin = os.path.join(venv, "bin")
    vpy = os.path.join(vbin, "python")
    run([vpy, "-m", "pip", "install", "-q", whl])

    outside = os.path.join(tmp, "elsewhere")
    os.makedirs(outside)
    env = dict(os.environ)
    for var in ("PYTHONPATH", "PALADIN_PORT"):
        env.pop(var, None)
    env["AI_PALADIN_CONFIG_DIR"] = os.path.join(tmp, "config")
    env["AI_PALADIN_LOG_DIR"] = os.path.join(tmp, "logs")
    env["HOME"] = os.path.join(tmp, "home")
    os.makedirs(env["HOME"])

    step("4. importing from the installed copy")
    out = run([vpy, "-c", "import ai_paladin, ai_paladin.paths as p; "
               "print(ai_paladin.__file__); print(p.BASE)"],
              cwd=outside, env=env, capture_output=True, text=True).stdout
    mod_file, base = out.strip().splitlines()
    assert mod_file.startswith(venv), mod_file
    assert base.startswith(venv) and base.endswith("_shipped"), base

    step("5. ai-paladin --where")
    where = run([os.path.join(vbin, "ai-paladin"), "--where"], cwd=outside,
                env=env, capture_output=True, text=True).stdout
    for name in config_layers.SHIPPED_FILES:
        assert name in where, (name, where)

    step("6. booting the router from the wheel")
    port = free_port()
    log = open(os.path.join(tmp, "router.log"), "w")
    proc = subprocess.Popen([os.path.join(vbin, "ai-paladin"), "--port",
                             str(port)], cwd=outside, env=env, stdout=log,
                            stderr=subprocess.STDOUT)
    base_url = "http://127.0.0.1:%d" % port
    try:
        posture = None
        for _ in range(120):
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(base_url + "/api/posture",
                                            timeout=2) as r:
                    posture = json.load(r)
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.25)
        assert posture, "router did not answer; see %s" % log.name
        assert posture["guard"]["self_test"]["passed"], posture["guard"]
        with urllib.request.urlopen(base_url + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
        assert 'name="ai-paladin-token"' in html, "dashboard has no token"
        req = urllib.request.Request(
            base_url + "/api/posture", data=b'{"mode": "slow"}',
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("untokened POST was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, exc.code
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()

    step("7. ai-paladin-hook from the wheel")
    hook = os.path.join(vbin, "ai-paladin-hook")

    def call(cmd):
        payload = json.dumps({"hook_event_name": "PreToolUse",
                              "tool_name": "Bash",
                              "tool_input": {"command": cmd},
                              "session_id": "wheel-smoke", "cwd": outside})
        return run([hook], input=payload, text=True, cwd=outside, env=env,
                   capture_output=True, check=False).returncode

    assert call("ls") == 0
    assert call("rm -rf /") == 2

    step("all steps passed (%s)" % wheels[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
