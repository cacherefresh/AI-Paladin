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

import re                                                   # noqa: E402

from ai_paladin import config_layers, hook, shell_scan      # noqa: E402
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


class ShellSpelling(_HookCase):
    """A credential path is recognised however the shell spells it."""

    def test_respelled_credential_paths_refused(self):
        link = os.path.join(WS, "keys")
        if not os.path.islink(link):
            os.symlink(os.path.expanduser("~/.ssh"), link)
        for c in ["cat ~/.ss''h/id_rsa", 'cat ~/."s"sh/id_rsa',
                  "cat ~/.s\\sh/id_rsa", "cat ${HOME}/.a''ws/credentials",
                  "D=.ss''h; cat ~/$D/id_rsa", "cat .e''nv",
                  "cp .en\"v\".local /tmp/x", "cat keys/id_rsa",
                  "head --lines=3 --file=x ~/.a\"ws\"/config",
                  "sh -c \"cat ~/.ss''h/id_rsa\""]:
            with self.subTest(c=c):
                self.refused(bash(c), "credential-path-access")

    def test_respelled_tamper_refused(self):
        self.refused(bash("ai-paladin-hook --rel''ease s1"), "hook-tamper")

    def test_lookalikes_pass(self):
        for c in ["cat env.py", "ls .venv/bin", "cat .envrc", "echo ssh",
                  "git log --format=%H", "cat src/environment.py"]:
            with self.subTest(c=c):
                self.allowed(bash(c))


class ShellWrites(_HookCase):
    """Files a Bash command writes, renames or deletes get the Write tool's
    protections: protected files, and write_scope.deny."""

    def test_writes_into_denied_paths_refused(self):
        for c in ["echo hi > /etc/motd", "echo hi >> /etc/motd",
                  "echo hi 2>/etc/motd", "echo hi &>/etc/motd",
                  "echo hi | tee -a /etc/motd", "cp x /etc/motd",
                  "cp -t /usr/local/bin x", "mv x /usr/bin/ls",
                  "install -m 755 x /usr/local/bin/x", "touch /etc/x",
                  "ln -sf x /etc/x", "sed -i s/a/b/ /etc/hosts",
                  "dd if=x of=/etc/motd", "rm /usr/bin/python3",
                  "truncate -s 0 /etc/motd", "chmod +x /usr/bin/x",
                  "curl -o /etc/x https://example.com",
                  "tar xzf a.tgz -C /usr", "cd /etc && echo hi > motd",
                  "cd / ; cd etc ; echo hi > motd",
                  "sh -c 'echo hi > /etc/motd'",
                  "echo hi > /e''tc/motd", "echo hi > /e*c/motd",
                  "rm -rf backup/old", "rm .git/objects/ab/cd",
                  "find backup -delete"]:
            with self.subTest(c=c):
                self.refused(bash(c))

    def test_hook_evidence_and_settings_refused(self):
        logs = os.path.join(os.path.expanduser("~"), ".local", "state",
                            "ai-paladin")
        for c in ["rm ~/.local/state/ai-paladin/logs/hooks.jsonl",
                  ": > ~/.local/state/ai-paladin/logs/hooks.jsonl",
                  "truncate -s0 %s/logs/hooks.jsonl" % logs,
                  "cd ~/.local/state && rm -rf ai-paladin",
                  "rm -rf ~/.local/state", "mv ~/.config ~/old-config",
                  "rm -rf ~/.claude", "rm -rf .claude",
                  "find ~/.local -delete"]:
            with self.subTest(c=c):
                self.refused(bash(c), "hook-tamper")

    def test_ordinary_writes_pass(self):
        for c in ["echo hi > out.txt", "ls > /dev/null 2>&1", "make 2>&1",
                  "cmd >&2", "cp a b", "mv old new", "rm -rf ./dist",
                  "rm -rf /tmp/build", "mkdir -p ~/scratch/x",
                  "sed -i s/a/b/ src/a.py", "tee log.txt < in",
                  "chmod +x run.sh", "tar czf out.tgz src",
                  "curl -o page.html https://example.com",
                  "touch ~/scratch/stamp", "cd src && echo x > y"]:
            with self.subTest(c=c):
                self.allowed(bash(c))


class Interpreters(_HookCase):
    """Code run by an interpreter - inline or a script the agent wrote - is
    checked for the files it writes and the commands it runs."""

    def script(self, name, text):
        p = os.path.join(WS, name)
        with open(p, "w") as fh:
            fh.write(text)
        os.chmod(p, 0o755)
        return name

    def test_inline_code_writes_refused(self):
        for c in ["python3 -c \"open('/etc/ai-paladin-probe','w').write('x')\"",
                  "python3 -c 'import os; os.remove(\"/usr/bin/x\")'",
                  "python3 -c 'import pathlib; pathlib.Path(\"/etc\")"
                  ".joinpath(\"x\"); pathlib.Path(\"/etc/x\").write_text(\"y\")'",
                  "python3 -c 'import shutil; shutil.rmtree(\"backup\")'",
                  "python3 -c 'P=\"/et\" + \"c/x\"; open(P, \"a\")'",
                  "python3 -c 'import os; os.system(\"echo x > /etc/motd\")'",
                  "python3 -c 'import subprocess; subprocess.run("
                  "[\"pip\", \"install\", \"evilpkg==1.0\"])'",
                  "python3 - <<'EOF'\nopen('/etc/x', 'w')\nEOF",
                  "perl -e 'open(F, \">/etc/motd\"); print F 1'",
                  "perl -pi -e 's/a/b/' /etc/hosts",
                  "node -e \"require('fs').writeFileSync('/etc/x','y')\"",
                  "ruby -e 'File.write(\"/etc/x\", \"y\")'"]:
            with self.subTest(c=c):
                self.refused(bash(c))

    def test_inline_code_tamper_and_credentials_refused(self):
        self.refused(bash("python3 -c 'import os; os.remove(os.path.expanduser("
                          "\"~/.local/state/ai-paladin/logs/hooks.jsonl\"))'"),
                     "hook-tamper")
        self.refused(bash("python3 -c 'print(open(\"/root/.s\" + \"sh/id_rsa\")"
                          ".read())'"), "credential-path-access")

    def test_agent_written_scripts_refused(self):
        cases = [
            ("w1.py", "open('/etc/motd', 'w').write('x')\n", "python3 w1.py"),
            ("w2.py", "#!/usr/bin/env python3\nimport os\n"
                      "os.unlink(os.path.expanduser('~/.local/state/ai-paladin/"
                      "logs/hooks.jsonl'))\n", "./w2.py"),
            ("w3.sh", "#!/bin/sh\necho x > /etc/motd\n", "bash w3.sh"),
            ("w4.sh", "pip install evilpkg==1.0\n", "sh ./w4.sh"),
            ("w5.sh", "rm -rf ~/.claude\n", ". ./w5.sh"),
            ("w6.sh", "#!/bin/bash\ncat ~/.ss''h/id_rsa\n", "./w6.sh"),
            ("w7.py", "import subprocess\nsubprocess.run('echo x > /etc/m', "
                      "shell=True)\n", "python3 -u w7.py --flag"),
            ("w8.py", "open('/usr/x', 'w')\n", "python3 < w8.py"),
        ]
        for name, text, cmd in cases:
            self.script(name, text)
            with self.subTest(cmd=cmd):
                self.refused(bash(cmd))

    def test_ordinary_code_passes(self):
        self.script("ok.py", "import json\nopen('out.json', 'w').write("
                             "json.dumps({'a': 1}))\nprint(open('/etc/hosts')"
                             ".read())\n")
        self.script("ok.sh", "#!/bin/sh\nmake test > build.log 2>&1\n")
        for c in ["python3 -c 'print(1)'", "python3 -m pytest -q",
                  "python3 ok.py", "./ok.sh", "bash ok.sh",
                  "python3 -c \"open('out.txt','w').write('x')\"",
                  "python3 -c \"print(open('/etc/hosts').read())\"",
                  "python3 -c 's=\"a\".replace(\"a\", \"/etc/x\")'",
                  "node -e 'console.log(1)'", "python3 missing.py"]:
            with self.subTest(c=c):
                self.allowed(bash(c))


class OtherTools(_HookCase):
    """Tools beyond the file and shell tools reach the hook and are checked."""

    def test_matcher_is_a_regex_covering_them(self):
        rx = re.compile("^(?:%s)$" % hook.MATCHER)
        for name in ["Bash", "Write", "Read", "WebFetch", "WebSearch", "Task",
                     "Agent", "mcp__filesystem__write_file", "mcp__github__x"]:
            self.assertTrue(rx.match(name), name)
        self.assertFalse(rx.match("TodoWrite"))

    def test_mcp_and_webfetch_paths_checked(self):
        self.refused(tool("mcp__filesystem__read_file", path="~/.ssh/id_rsa"),
                     "credential-path-access")
        self.refused(tool("mcp__filesystem__write_file", path="/etc/motd",
                          content="x"), "out-of-scope-path")
        self.refused(tool("mcp__fs__move_file", source="a",
                          destination="~/.claude/settings.json"),
                     "hook-tamper")
        self.refused(tool("WebFetch", url="file:///root/.aws/credentials",
                          prompt="x"), "credential-path-access")
        self.allowed(tool("mcp__filesystem__write_file",
                          path=os.path.join(WS, "a.txt"), content="x"))
        self.allowed(tool("mcp__github__get_file", path="src/a.py",
                          repo="o/r"))
        self.allowed(tool("WebFetch", url="https://example.com", prompt="x"))
        self.allowed(tool("WebSearch", query="python wheels"))
        self.allowed(tool("Task", description="d", prompt="p"))

    def test_paused_session_stops_web_and_subagents(self):
        logdir = tempfile.mkdtemp(prefix="ai-paladin-hooklog-")
        with mock.patch.object(hook, "_state_path", lambda s: os.path.join(
                logdir, s + ".json")), \
                mock.patch.object(hook, "_log", lambda r: None):
            hook._save_state("p1", {"blocked": 9, "paused": True, "writes": []})
            for t in [tool("WebFetch", url="https://example.com", prompt="x"),
                      tool("WebSearch", query="x"), tool("Task", prompt="x"),
                      tool("mcp__github__list_issues", repo="o/r")]:
                t["session_id"] = "p1"
                with self.subTest(tool=t["tool_name"]):
                    allowed, msg = hook.decide(t)
                    self.assertFalse(allowed)
                    self.assertIn("fence-probing", msg)


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

    def test_write_targets(self):
        def wt(c):
            return [t for s in shell_scan.scan(c).segments
                    for t in shell_scan.write_targets(s)]
        self.assertEqual(wt("cp -r a b c/"), [("c/", "write")])
        self.assertEqual(wt("rm -rf x y"), [("x", "destroy"), ("y", "destroy")])
        self.assertEqual(wt("sed -e s/a/b/ -i f g"), [("f", "write"),
                                                       ("g", "write")])
        self.assertEqual(wt("chmod -x f"), [("f", "write")])
        self.assertEqual(wt("chmod 644 f"), [("f", "write")])
        self.assertEqual(wt("ls 2>&1 >o"), [("o", "write")])

    def test_expand_word(self):
        env = {"HOME": "/home/u", "D": ".ssh"}
        self.assertEqual(shell_scan.expand_word("~/$D/k", env, "/w"),
                         ["/home/u/.ssh/k"])
        self.assertEqual(shell_scan.expand_word("${D}x$NOPE", env, "/w"),
                         [".sshx$NOPE"])
        self.assertEqual(shell_scan.word_paths("of=~/x", env, "/w"),
                         ["of=~/x", "/home/u/x"])


if __name__ == "__main__":
    unittest.main()
