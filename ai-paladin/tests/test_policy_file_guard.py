"""
The hook refuses an agent that edits AI-Paladin's own enforcement files.

Run from ai-paladin/:  python3 -m unittest tests.test_policy_file_guard -v

AGENTS.md: router/keywords.yaml, router/policy.yaml, config/keywords.yaml,
security/policies/ and security/monitors/ are enforcement, not
documentation. These tests pin that the PreToolUse hook (rule hook-tamper)
refuses changes to them by every route it inspects - the file tools, Bash
writes, interpreter code and MCP tools - in this checkout, in any other
AI-Paladin checkout, and only there: a file of the same name in an
unrelated project is not affected. Reading them stays allowed.

LIMIT: like every hook rule, this inspects tool calls. A program that
rewrites these files without the hook seeing the path (git checkout of an
old revision, a path computed at run time) is not caught; the boundary
for that is OS-level (docs/ROADMAP.md, section 9).
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

from ai_paladin import config_layers, hook, paths           # noqa: E402
from ai_paladin.hook import Refused, evaluate               # noqa: E402
from ai_paladin.security import monitors                    # noqa: E402

CMDS = config_layers.load_whole("commands.yaml")[0]
PKGS = config_layers.load_whole("packages.yaml")[0]
CRED = monitors.credential_globs()

POLICY = ["router/keywords.yaml", "router/policy.yaml", "config/keywords.yaml",
          "security/policies/commands.yaml", "security/policies/packages.yaml",
          "security/monitors/behavioral_rules.yaml"]


def call(name, cwd, **ti):
    return {"tool_name": name, "tool_input": ti, "session_id": "pol",
            "cwd": cwd}


def bash(cmd, cwd):
    return call("Bash", cwd, command=cmd)


class _Case(unittest.TestCase):
    workspace = None

    def setUp(self):
        self.env = mock.patch.dict(os.environ,
                                   {"CLAUDE_PROJECT_DIR": self.workspace})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def refused(self, c):
        with self.assertRaises(Refused) as ctx:
            evaluate(c, CMDS, PKGS, CRED)
        self.assertEqual(ctx.exception.rule, "hook-tamper",
                         ctx.exception.reason)

    def allowed(self, c):
        try:
            evaluate(c, CMDS, PKGS, CRED)
        except Refused as r:
            self.fail("refused %r: %s" % (c["tool_input"], r.reason))


class ThisCheckout(_Case):
    """The repository as an agent working in it sees it: the project folder
    is the repo root, the tree is ai-paladin/ (paths.BASE)."""

    workspace = os.path.dirname(paths.BASE)
    base = paths.BASE

    def test_file_tools_refused(self):
        for rel in POLICY:
            for name in ("Write", "Edit", "MultiEdit"):
                with self.subTest(tool=name, rel=rel):
                    self.refused(call(name, self.workspace,
                                      file_path=os.path.join(self.base, rel)))
        self.refused(call("Write", self.workspace,
                          file_path=os.path.join(self.base, "security",
                                                 "policies", "new.yaml")))
        self.refused(call("Edit", self.base,
                          file_path="../ai-paladin/router/../router/policy.yaml"))

    def test_bash_writes_refused(self):
        for c in ["sed -i s/block/allow/ ai-paladin/router/policy.yaml",
                  "echo '- pattern: x' >> ai-paladin/security/policies/commands.yaml",
                  "cp /tmp/x ai-paladin/security/monitors/behavioral_rules.yaml",
                  "mv ai-paladin/config/keywords.yaml /tmp/",
                  "rm -rf ai-paladin/security", "rm -rf ai-paladin/router",
                  "cd ai-paladin && : > router/keywords.yaml",
                  "cd ai-paladin/security && rm -r policies",
                  "python3 -c \"open('ai-paladin/router/policy.yaml','w')\"",
                  "sh -c 'tee ai-paladin/security/policies/packages.yaml < x'"]:
            with self.subTest(c=c):
                self.refused(bash(c, self.workspace))

    def test_mcp_write_refused(self):
        self.refused(call("mcp__filesystem__write_file", self.workspace,
                          path=os.path.join(self.base, "router", "policy.yaml"),
                          content="x"))

    def test_reading_and_neighbours_allowed(self):
        for c in [call("Read", self.workspace,
                       file_path=os.path.join(self.base, "router", "policy.yaml")),
                  bash("cat ai-paladin/router/policy.yaml", self.workspace),
                  bash("git diff ai-paladin/security/", self.workspace),
                  bash("grep -r block ai-paladin/security/policies",
                       self.workspace)]:
            with self.subTest(c=c["tool_input"]):
                self.allowed(c)
        self.assertFalse(hook._protected(os.path.join(self.base, "router",
                                                      "README.md")))
        self.assertFalse(hook._protected(os.path.join(self.base, "security",
                                                      "README.md")))


class AnotherCheckout(_Case):
    """A second AI-Paladin checkout (a fork, a worktree) is guarded too."""

    workspace = os.path.realpath(tempfile.mkdtemp(prefix="ai-paladin-fork-"))

    @classmethod
    def setUpClass(cls):
        os.makedirs(os.path.join(cls.workspace, "ai_paladin"))
        open(os.path.join(cls.workspace, "ai_paladin", "hook.py"), "w").close()
        for rel in POLICY:
            p = os.path.join(cls.workspace, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()

    def test_refused(self):
        self.refused(call("Write", self.workspace,
                          file_path=os.path.join(self.workspace, "router",
                                                 "policy.yaml")))
        self.refused(bash("echo x > security/monitors/behavioral_rules.yaml",
                          self.workspace))
        self.refused(bash("rm -rf security", self.workspace))


class UnrelatedProject(_Case):
    """Files that only share a name, outside any AI-Paladin tree, are the
    project's own business."""

    workspace = os.path.realpath(tempfile.mkdtemp(prefix="some-project-"))

    def test_allowed(self):
        for rel in POLICY:
            with self.subTest(rel=rel):
                self.allowed(call("Write", self.workspace,
                                  file_path=os.path.join(self.workspace, rel)))
        self.allowed(bash("echo x > router/policy.yaml", self.workspace))
        self.allowed(bash("rm -rf security", self.workspace))


if __name__ == "__main__":
    unittest.main()
