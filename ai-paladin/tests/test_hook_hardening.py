"""
The hardened hook: the bypass families closed in bugfix/hook-bypasses.

Run from ai-paladin/:  python3 -m unittest tests.test_hook_hardening -v

tests/test_hook_bypasses.py pins the 11 original bypasses, one test each.
This file covers each fix more widely - the other spellings of the same
trick - and pins the ordinary commands that must still pass, so a fix that
over-blocks shows up here.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.environ.setdefault("AI_PALADIN_LOG_DIR",
                      tempfile.mkdtemp(prefix="ai-paladin-test-"))

from ai_paladin import config_layers, shell_scan            # noqa: E402
from ai_paladin.hook import Refused, evaluate               # noqa: E402
from ai_paladin.security import monitors                    # noqa: E402

CMDS = config_layers.load_whole("commands.yaml")[0]
PKGS = config_layers.load_whole("packages.yaml")[0]
CRED = monitors.credential_globs()
WS = os.path.realpath(tempfile.mkdtemp(prefix="ai-paladin-ws-"))


def bash(cmd, cwd=WS):
    return {"tool_name": "Bash", "tool_input": {"command": cmd},
            "session_id": "hard", "cwd": cwd}


def tool(name, **ti):
    return {"tool_name": name, "tool_input": ti, "session_id": "hard",
            "cwd": WS}


class _HookCase(unittest.TestCase):

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": WS})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def refused(self, call, rule=None):
        with self.assertRaises(Refused) as ctx:
            evaluate(call, CMDS, PKGS, CRED)
        if rule:
            self.assertEqual(ctx.exception.rule, rule, ctx.exception.reason)

    def allowed(self, call):
        try:
            evaluate(call, CMDS, PKGS, CRED)
        except Refused as r:
            self.fail("refused %r: %s" % (call["tool_input"], r.reason))


class ShellIndirection(_HookCase):
    """A command wrapped in another shell is checked like the bare one."""

    def test_wrapped_installs_refused(self):
        for c in ["sh -c 'pip install evilpkg==1.0'",
                  "bash -lc 'pip install evilpkg==1.0'",
                  "zsh -c 'cd x; pip install evilpkg==1.0'",
                  "sudo -u root sh -c 'npm i left-pad@1.3.0'",
                  "env FOO=1 bash -c \"pip install evilpkg==1.0\"",
                  "timeout 30 sh -c 'pip install evilpkg==1.0'",
                  "echo x | xargs -n1 sh -c 'pip install evilpkg==1.0'",
                  "eval 'pip install evilpkg==1.0'",
                  "echo $(pip install evilpkg==1.0)",
                  "echo `pip install evilpkg==1.0`",
                  "bash -c \"bash -c 'pip install evilpkg==1.0'\"",
                  "bash <<EOF\npip install evilpkg==1.0\nEOF",
                  "bash <<< 'pip install evilpkg==1.0'",
                  "(pip install evilpkg==1.0)",
                  "ls\npip install evilpkg==1.0"]:
            with self.subTest(c=c):
                self.refused(bash(c), "packages.yaml")

    def test_wrapped_blocked_and_tamper_commands_refused(self):
        self.refused(bash("sh -c 'history -c'"), "commands.yaml")
        self.refused(bash("bash -c 'ai-paladin-hook --release s1'"),
                     "hook-tamper")

    def test_runaway_nesting_refused(self):
        c = "ls"
        for _ in range(10):
            c = "sh -c %s" % shell_scan.shlex.quote(c)
        self.refused(bash(c), "commands.yaml")

    def test_ordinary_wrapped_commands_pass(self):
        for c in ["sh -c 'ls -la'", "bash -c \"git status && make test\"",
                  "sh -c 'pip install requests==2.32.3'",
                  "echo \"$(date)\"", "bash scripts_missing.sh",
                  "cat <<EOF > notes.txt\npip install anything\nEOF"]:
            with self.subTest(c=c):
                self.allowed(bash(c))


class ShellScanUnit(unittest.TestCase):

    def test_segments_and_inner(self):
        sc = shell_scan.scan("A=1 sudo env B=2 sh -c 'x; y' && ls | wc -l")
        self.assertEqual([s.words for s in sc.segments],
                         [["sh", "-c", "x; y"], ["ls"], ["wc", "-l"]])
        self.assertEqual(sc.inner, ["x; y"])

    def test_operator_runs_split(self):
        sc = shell_scan.scan("(cd x);ls 2>&1 >out")
        self.assertEqual([s.words for s in sc.segments], [["cd", "x"], ["ls"]])
        self.assertEqual(sc.segments[1].redirects, [(">&", "1"), (">", "out")])


if __name__ == "__main__":
    unittest.main()
