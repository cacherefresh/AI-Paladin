"""
The 11 PreToolUse hook bypasses found before distribution, now regression
tests.

Run from ai-paladin/:  python3 -m unittest tests.test_hook_bypasses -v

Each test states what the hook SHOULD refuse. They were pinned as expected
failures (Rob, 2026-11-28: the hook was advisory, hardening deferred) and
were closed on bugfix/hook-bypasses, one commit per root cause:

    nested shells (sh -c, bash -c)            ai_paladin/shell_scan.py
    shell quoting in credential paths         shell_scan.word_paths
    files written by Bash (>, rm, : >)        shell_scan.write_targets
    files written by interpreter code         ai_paladin/code_scan.py
    tools outside the matcher                 hook.MATCHER

Wider coverage of each fix is in tests/test_hook_hardening.py. A bypass that
cannot be closed at the hook level goes back here as @expectedFailure with
a reason pointing at the OS-level boundary goal (docs/ROADMAP.md,
section 9). Never make one pass by editing security/policies/ or
security/monitors/ to suit the test.
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

from ai_paladin import config_layers, hook                  # noqa: E402
from ai_paladin.hook import Refused, evaluate               # noqa: E402
from ai_paladin.security import monitors                    # noqa: E402

HARDENING_DEFERRED = ("a known hook bypass has reopened; see "
                      "tests/test_hook_bypasses.py and ROADMAP.md s.9")

CMDS = config_layers.load_whole("commands.yaml")[0]
PKGS = config_layers.load_whole("packages.yaml")[0]
CRED = monitors.credential_globs()
WS = os.path.realpath(tempfile.mkdtemp(prefix="ai-paladin-ws-"))


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd},
            "session_id": "bypass", "cwd": WS}


class KnownHookBypasses(unittest.TestCase):
    """Each was a bypass; each must now be refused."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": WS})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def assertRefused(self, call):
        try:
            evaluate(call, CMDS, PKGS, CRED)
        except Refused:
            return
        self.fail("hook allowed %r (%s)" % (call["tool_input"],
                                             HARDENING_DEFERRED))

    # -- package installs ---------------------------------------------------
    # `pip install evilpkg==1.0` is refused; wrapped in a shell, it was not.

    def test_pip_install_inside_sh_c(self):
        self.assertRefused(bash("sh -c 'pip install evilpkg==1.0'"))

    def test_pip_install_inside_bash_c(self):
        self.assertRefused(bash('bash -c "pip install evilpkg==1.0"'))

    # -- credential paths ---------------------------------------------------
    # `cat ~/.ssh/id_rsa` is refused; quote-splitting the path got past.

    def test_quote_split_ssh_path(self):
        self.assertRefused(bash("cat ~/.ss''h/id_rsa"))

    # -- write scope --------------------------------------------------------
    # Write/Edit into /etc is refused; Bash writes were not checked.

    def test_shell_redirect_into_etc(self):
        self.assertRefused(bash("echo hi > /etc/motd"))

    def test_python_c_write_into_etc(self):
        self.assertRefused(bash(
            "python3 -c \"open('/etc/ai-paladin-probe','w').write('x')\""))

    # -- tampering with the hook's own evidence ------------------------------

    def test_rm_hook_audit_log(self):
        self.assertRefused(bash("rm ~/.local/state/ai-paladin/logs/hooks.jsonl"))

    def test_truncate_hook_audit_log(self):
        self.assertRefused(bash(
            ": > ~/.local/state/ai-paladin/logs/hooks.jsonl"))

    # -- tools the hook never sees ------------------------------------------
    # Claude Code only calls the hook for tools named in the matcher it is
    # installed with; anything else runs unchecked, so these must be in it.

    def test_matcher_covers_webfetch(self):
        self.assertIn("WebFetch", hook.MATCHER.split("|"), HARDENING_DEFERRED)

    def test_matcher_covers_websearch(self):
        self.assertIn("WebSearch", hook.MATCHER.split("|"), HARDENING_DEFERRED)

    def test_matcher_covers_task(self):
        self.assertIn("Task", hook.MATCHER.split("|"), HARDENING_DEFERRED)

    def test_matcher_covers_mcp_tools(self):
        self.assertTrue(any(p.startswith("mcp__") for p in hook.MATCHER.split("|")),
                        HARDENING_DEFERRED)


class BypassBaselineStillHolds(unittest.TestCase):
    """The direct forms of the bypasses above ARE refused today. If one of
    these fails, the hook regressed; that is a real failure, not deferred."""

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": WS})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_direct_pip_install_refused(self):
        with self.assertRaises(Refused):
            evaluate(bash("pip install evilpkg==1.0"), CMDS, PKGS, CRED)

    def test_direct_ssh_key_read_refused(self):
        with self.assertRaises(Refused):
            evaluate(bash("cat $HOME/.ssh/id_rsa"), CMDS, PKGS, CRED)

    def test_whole_quoted_ssh_segment_refused(self):
        # Quoting a whole path segment was always caught.
        with self.assertRaises(Refused):
            evaluate(bash('cat ~/".ssh"/id_rsa'), CMDS, PKGS, CRED)

    def test_write_tool_into_etc_refused(self):
        call = {"tool_name": "Write", "session_id": "bypass", "cwd": WS,
                "tool_input": {"file_path": "/etc/motd", "content": "x"}}
        with self.assertRaises(Refused):
            evaluate(call, CMDS, PKGS, CRED)


if __name__ == "__main__":
    unittest.main()
