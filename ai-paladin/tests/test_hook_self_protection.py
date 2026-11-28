"""
The hook refuses an agent that edits, overwrites or deletes the hook itself.

Run from ai-paladin/:  python3 -m unittest tests.test_hook_self_protection -v

Rule hook-tamper. Protected: the modules the hook runs (ai_paladin/hook.py,
shell_scan.py, code_scan.py, config_layers.py, paths.py, security/
monitors.py and the package __init__ files) wherever the hook runs from -
this checkout or an installed package - and in any AI-Paladin checkout; the
hooks/pre_tool_use.py wrapper; the installed `ai-paladin-hook` command; and
(already) the Claude Code settings entry that runs it. Every route the hook
inspects applies: file tools, MCP write tools, Bash writes, interpreter code
and scripts. Reading the code, and editing the rest of the package, stay
allowed.

LIMIT: as for every hook rule - a change the hook cannot see (a path
computed at run time, `git checkout` of an old revision) is not caught; the
boundary for that is OS-level (docs/ROADMAP.md, section 9).
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
REPO = os.path.dirname(paths.BASE)            # the project folder: repo root
PKG = os.path.dirname(os.path.abspath(hook.__file__))


def call(name, **ti):
    return {"tool_name": name, "tool_input": ti, "session_id": "self",
            "cwd": REPO}


def bash(cmd, cwd=REPO):
    return {"tool_name": "Bash", "tool_input": {"command": cmd},
            "session_id": "self", "cwd": cwd}


class HookSelfProtection(unittest.TestCase):

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": REPO})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def refused(self, c):
        with self.assertRaises(Refused) as ctx:
            evaluate(c, CMDS, PKGS, CRED, dict(hook.HOOK_SETTING_DEFAULTS))
        self.assertEqual(ctx.exception.rule, "hook-tamper",
                         ctx.exception.reason)

    def allowed(self, c):
        try:
            evaluate(c, CMDS, PKGS, CRED, dict(hook.HOOK_SETTING_DEFAULTS))
        except Refused as r:
            self.fail("refused %r: %s" % (c["tool_input"], r.reason))

    def test_file_tools_refused(self):
        for rel in hook.HOOK_CODE:
            p = os.path.join(os.path.dirname(PKG), rel)
            for name in ("Write", "Edit", "MultiEdit"):
                with self.subTest(tool=name, rel=rel):
                    self.refused(call(name, file_path=p, content="x"))
        self.refused(call("Write", file_path=os.path.join(
            paths.BASE, "hooks", "pre_tool_use.py"), content="x"))
        self.refused(call("Edit", file_path="ai-paladin/ai_paladin/../ai_paladin/hook.py"))
        self.refused(call("mcp__filesystem__write_file",
                          path=os.path.join(PKG, "hook.py"), content="x"))
        self.refused(call("Write", file_path=os.path.join(
            REPO, ".claude", "settings.local.json"), content="{}"))

    def test_shell_and_code_refused(self):
        for c in ["sed -i s/return 2/return 0/ ai-paladin/ai_paladin/hook.py",
                  "echo 'def main(): return 0' > ai-paladin/ai_paladin/hook.py",
                  "cp /tmp/x ai-paladin/ai_paladin/shell_scan.py",
                  "rm ai-paladin/ai_paladin/code_scan.py",
                  "mv ai-paladin/ai_paladin/hook.py /tmp/",
                  "truncate -s0 ai-paladin/hooks/pre_tool_use.py",
                  "rm -rf ai-paladin/ai_paladin",
                  "rm -rf ai-paladin/ai_paladin/security",
                  "cd ai-paladin/ai_paladin && : > hook.py",
                  "sh -c 'tee ai-paladin/ai_paladin/paths.py < x'",
                  "python3 -c \"open('ai-paladin/ai_paladin/hook.py','w')\"",
                  "python3 -c \"import os; os.remove('ai-paladin/ai_paladin"
                  "/security/monitors.py')\""]:
            with self.subTest(c=c):
                self.refused(bash(c))

    def test_installed_command_and_package_refused(self):
        d = os.path.realpath(tempfile.mkdtemp(prefix="ai-paladin-bin-"))
        cmd = os.path.join(d, "ai-paladin-hook")
        open(cmd, "w").close()
        with mock.patch("shutil.which", return_value=cmd):
            self.refused(bash("echo exit 0 > %s" % cmd))
            self.refused(call("Write", file_path=cmd, content="x"))
        # an installed copy: site-packages/ai_paladin/hook.py
        site = os.path.realpath(tempfile.mkdtemp(prefix="site-packages-"))
        os.makedirs(os.path.join(site, "ai_paladin"))
        open(os.path.join(site, "ai_paladin", "hook.py"), "w").close()
        self.refused(bash("echo x > %s/ai_paladin/hook.py" % site))
        self.refused(bash("rm -rf %s/ai_paladin" % site, cwd=site))

    def test_reading_and_the_rest_of_the_package_allowed(self):
        for c in [call("Read", file_path=os.path.join(PKG, "hook.py")),
                  bash("cat ai-paladin/ai_paladin/hook.py"),
                  bash("git diff ai-paladin/ai_paladin/hook.py"),
                  call("Edit", file_path=os.path.join(PKG, "router",
                                                      "classifier.py")),
                  bash("echo x >> ai-paladin/ai_paladin/server/app.py"),
                  call("Write", file_path=os.path.join(
                      REPO, "ai-paladin", "tests", "test_new.py"))]:
            with self.subTest(c=c["tool_input"]):
                self.allowed(c)


if __name__ == "__main__":
    unittest.main()
