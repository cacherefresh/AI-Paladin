"""
Known PreToolUse hook bypasses, recorded as expected failures.

Run from ai-paladin/:  python3 -m unittest tests.test_hook_bypasses -v

Each test states what the hook SHOULD refuse and is marked expected-failure
because today it allows it. They are pinned here, not fixed, on purpose:

    HARDENING_DEFERRED - decided by Rob (2026-11-28): the hook is ADVISORY
    for now, a guardrail for honest mistakes. These bypasses are documented
    known limits. Making the hook a true security boundary is a roadmap goal
    (docs/ROADMAP.md, section 9); until each fix lands the enforcement logic
    in ai_paladin/hook.py and the policy files are unchanged.

When the hook is hardened, remove the @expectedFailure from the tests it now
passes; unittest reports an "unexpected success" for any bypass that gets
closed without updating this file. Never make one pass by editing
security/policies/ or security/monitors/ to suit the test.
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

HARDENING_DEFERRED = ("hook is advisory for now (Rob, 2026-11-28); a true "
                      "security boundary is a roadmap goal, ROADMAP.md s.9")

CMDS = config_layers.load_whole("commands.yaml")[0]
PKGS = config_layers.load_whole("packages.yaml")[0]
CRED = monitors.credential_globs()
WS = os.path.realpath(tempfile.mkdtemp(prefix="ai-paladin-ws-"))


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd},
            "session_id": "bypass", "cwd": WS}


class KnownHookBypasses(unittest.TestCase):
    """Each test fails today; see HARDENING_DEFERRED."""

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
    # `pip install evilpkg==1.0` is refused; wrapping it in a shell is not.

    def test_pip_install_inside_sh_c(self):
        self.assertRefused(bash("sh -c 'pip install evilpkg==1.0'"))

    def test_pip_install_inside_bash_c(self):
        self.assertRefused(bash('bash -c "pip install evilpkg==1.0"'))

    # -- credential paths ---------------------------------------------------
    # `cat ~/.ssh/id_rsa` is refused; shell quote-splitting the path is not.

    def test_quote_split_ssh_path(self):
        self.assertRefused(bash("cat ~/.ss''h/id_rsa"))

    # -- write scope --------------------------------------------------------
    # Write/Edit outside the project is refused; Bash writes are not checked.

    @unittest.expectedFailure
    def test_shell_redirect_into_etc(self):
        self.assertRefused(bash("echo hi > /etc/motd"))

    @unittest.expectedFailure
    def test_python_c_write_into_etc(self):
        self.assertRefused(bash(
            "python3 -c \"open('/etc/ai-paladin-probe','w').write('x')\""))

    # -- tampering with the hook's own evidence ------------------------------

    @unittest.expectedFailure
    def test_rm_hook_audit_log(self):
        self.assertRefused(bash("rm ~/.local/state/ai-paladin/logs/hooks.jsonl"))

    @unittest.expectedFailure
    def test_truncate_hook_audit_log(self):
        self.assertRefused(bash(
            ": > ~/.local/state/ai-paladin/logs/hooks.jsonl"))

    # -- tools the hook never sees ------------------------------------------
    # Claude Code only calls the hook for tools named in the matcher it is
    # installed with; anything else runs unchecked.

    @unittest.expectedFailure
    def test_matcher_covers_webfetch(self):
        self.assertIn("WebFetch", hook.MATCHER.split("|"), HARDENING_DEFERRED)

    @unittest.expectedFailure
    def test_matcher_covers_websearch(self):
        self.assertIn("WebSearch", hook.MATCHER.split("|"), HARDENING_DEFERRED)

    @unittest.expectedFailure
    def test_matcher_covers_task(self):
        self.assertIn("Task", hook.MATCHER.split("|"), HARDENING_DEFERRED)

    @unittest.expectedFailure
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
        # Quoting a whole path segment is caught; splitting one is not.
        with self.assertRaises(Refused):
            evaluate(bash('cat ~/".ssh"/id_rsa'), CMDS, PKGS, CRED)

    def test_write_tool_into_etc_refused(self):
        call = {"tool_name": "Write", "session_id": "bypass", "cwd": WS,
                "tool_input": {"file_path": "/etc/motd", "content": "x"}}
        with self.assertRaises(Refused):
            evaluate(call, CMDS, PKGS, CRED)


if __name__ == "__main__":
    unittest.main()
