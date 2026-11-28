"""
`ai-paladin uninstall` and the install manifest.

Run from ai-paladin/:  python3 -m unittest tests.test_uninstaller -v

The promise under test: uninstalling removes exactly what AI-Paladin recorded
adding outside Python - and is NOT a snapshot revert. Hooks that were already
there before install stay; hooks others add afterwards stay; an entry of ours
that was edited after install is flagged, not silently removed; answering n
changes nothing; and the person is told to run `pip uninstall ai-paladin`
afterwards (the command never runs pip itself).
"""

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.environ.setdefault("AI_PALADIN_LOG_DIR",
                      tempfile.mkdtemp(prefix="ai-paladin-test-"))

from ai_paladin import cli, hook, installs, paths           # noqa: E402

def rd(path):
    with open(path) as fh:
        return fh.read()


PROMPT = "Do you want me to remove the hooks I added outside of python?(Y/n)"
THIRD_PARTY = {"matcher": "Bash",
               "hooks": [{"type": "command", "command": "other-tool --check"}]}


class UninstallerTests(unittest.TestCase):

    def setUp(self):
        self.proj = tempfile.mkdtemp(prefix="ai-paladin-proj-")
        self.home = tempfile.mkdtemp(prefix="ai-paladin-home-")
        self.env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.proj,
                                                "HOME": self.home})
        self.env.start()
        self.cfg_dir = os.path.join(self.home, "cfg")
        self.cfg = mock.patch.object(paths, "CONFIG_DIR", self.cfg_dir)
        self.cfg.start()
        self.settings_path = hook.settings_file(False)

    def tearDown(self):
        self.cfg.stop()
        self.env.stop()

    # -- helpers ---------------------------------------------------------

    def write_settings(self, data, path=None):
        path = path or self.settings_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)

    def settings(self, path=None):
        with open(path or self.settings_path) as fh:
            return json.load(fh)

    def pre(self, path=None):
        return self.settings(path)["hooks"]["PreToolUse"]

    def install(self, *args):
        with mock.patch.object(sys, "stdout", io.StringIO()) as out:
            code = hook.main(["--install"] + list(args))
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def uninstall(self, args=(), answers=()):
        """Run `ai-paladin uninstall`; returns (code, stdout, input mock, pip mock)."""
        answers = list(answers)
        inp = mock.MagicMock(side_effect=answers if answers else EOFError)
        pip = mock.MagicMock()
        with mock.patch("builtins.input", inp), \
                mock.patch("subprocess.run", pip), \
                mock.patch.object(sys, "stdout", io.StringIO()) as out, \
                mock.patch.object(sys, "stderr", io.StringIO()) as err:
            code = cli.main(["uninstall"] + list(args))
        return code, out.getvalue() + err.getvalue(), inp, pip

    def our_command(self):
        return hook.hook_command(self.settings_path)

    def edit_our_entry(self, new_text):
        data = self.settings()
        for e in data["hooks"]["PreToolUse"]:
            if hook._is_ours(e):
                e["hooks"][0]["command"] += new_text
        self.write_settings(data)

    # -- the manifest ----------------------------------------------------

    def test_install_records_what_we_added(self):
        self.install()
        path = os.path.join(self.cfg_dir, "install_manifest.json")
        self.assertEqual(installs.manifest_path(), path)
        with open(path) as fh:
            m = json.load(fh)
        rec = m["installs"][0]
        self.assertEqual(rec["file"], self.settings_path)
        self.assertEqual(rec["already_present"], [])
        added = rec["added"][0]
        entry = self.pre()[0]
        self.assertEqual(added["fingerprint"], installs.fingerprint(entry))
        self.assertEqual(added["matcher"], entry["matcher"])
        self.assertIn("pre_tool_use.py", added["summary"])

    def test_fingerprint_ignores_key_order(self):
        a = {"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}
        b = {"hooks": [{"command": "x", "type": "command"}], "matcher": "Bash"}
        self.assertEqual(installs.fingerprint(a), installs.fingerprint(b))
        b["hooks"][0]["command"] = "y"
        self.assertNotEqual(installs.fingerprint(a), installs.fingerprint(b))

    def test_manifest_follows_the_config_dir_env_var(self):
        """End to end, in real processes: $AI_PALADIN_CONFIG_DIR decides where
        the manifest lives, and `ai-paladin uninstall` reads it from there."""
        cfg = os.path.join(self.home, "elsewhere")
        env = dict(os.environ, AI_PALADIN_CONFIG_DIR=cfg, PYTHONPATH=_ROOT,
                   AI_PALADIN_LOG_DIR=os.path.join(self.home, "logs"))
        run = lambda *a, **k: subprocess.run(
            [sys.executable, "-m"] + list(a), env=env, capture_output=True,
            text=True, cwd=self.proj, **k)
        r = run("ai_paladin.hook", "--install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(cfg, "install_manifest.json")))
        r = run("ai_paladin", "uninstall", input="n\n")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(PROMPT, r.stdout)
        self.assertEqual(len(self.pre()), 1)                 # declined: kept
        r = run("ai_paladin", "uninstall", input="\n")        # Enter = Yes
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("hooks", self.settings())
        self.assertFalse(os.path.exists(os.path.join(cfg, "install_manifest.json")))

    # -- the prompt and the listing --------------------------------------

    def test_prompt_text_and_listing(self):
        self.write_settings({"hooks": {"PreToolUse": [THIRD_PARTY]}})
        self.install()
        fp = installs.fingerprint(self.pre()[-1])
        code, out, inp, pip = self.uninstall(answers=[""])
        self.assertEqual(code, 0, out)
        inp.assert_called_once_with(PROMPT + " ")            # character for character
        self.assertIn("REMOVE", out)
        self.assertIn(self.settings_path, out)               # file
        self.assertIn("PreToolUse matcher", out)             # config entry
        self.assertIn("pre_tool_use.py", out)
        self.assertIn("sha256 " + installs.short(fp), out)
        self.assertLess(out.index("REMOVE"), out.index("hook removed from"))

    def test_listing_comes_before_anything_is_removed(self):
        self.install()
        seen = {}

        def answer(prompt):
            seen["still_installed"] = len(self.pre()) == 1
            return "y"
        with mock.patch("builtins.input", answer), \
                mock.patch.object(sys, "stdout", io.StringIO()):
            cli.main(["uninstall"])
        self.assertTrue(seen["still_installed"])

    def test_empty_answer_means_yes(self):
        self.install()
        code, out, inp, pip = self.uninstall(answers=[""])
        self.assertEqual(code, 0)
        self.assertNotIn("hooks", self.settings())

    def test_unclear_answer_asks_again(self):
        self.install()
        code, out, inp, pip = self.uninstall(answers=["maybe", "y"])
        self.assertEqual(inp.call_count, 2)
        self.assertIn("Please answer y or n", out)
        self.assertNotIn("hooks", self.settings())

    # -- declining -------------------------------------------------------

    def test_declining_removes_nothing(self):
        self.write_settings({"model": "x", "hooks": {"PreToolUse": [THIRD_PARTY]}})
        self.install()
        before_settings = rd(self.settings_path)
        before_manifest = rd(installs.manifest_path())
        for answer in ("n", "N", "no"):
            code, out, inp, pip = self.uninstall(answers=[answer])
            self.assertEqual(code, 1, out)
            self.assertIn("Nothing changed", out)
            self.assertEqual(rd(self.settings_path), before_settings)
            self.assertEqual(rd(installs.manifest_path()), before_manifest)
            pip.assert_not_called()

    def test_no_one_to_answer_removes_nothing(self):
        self.install()
        before = rd(self.settings_path)
        code, out, inp, pip = self.uninstall()               # input raises EOFError
        self.assertEqual(code, 1)
        self.assertIn("--yes", out)
        self.assertEqual(rd(self.settings_path), before)

    def test_dry_run_lists_and_changes_nothing(self):
        self.install()
        before = rd(self.settings_path)
        code, out, inp, pip = self.uninstall(["--dry-run"])
        self.assertEqual(code, 0)
        inp.assert_not_called()
        self.assertIn("REMOVE", out)
        self.assertIn("Dry run", out)
        self.assertEqual(rd(self.settings_path), before)
        self.assertTrue(os.path.exists(installs.manifest_path()))

    # -- clean removal ---------------------------------------------------

    def test_clean_removal_leaves_everything_else_as_it_was(self):
        original = {"model": "x", "permissions": {"allow": ["Read"]},
                    "hooks": {"PreToolUse": [copy.deepcopy(THIRD_PARTY)],
                              "PostToolUse": [{"matcher": "*", "hooks": [
                                  {"type": "command", "command": "fmt"}]}]}}
        self.write_settings(copy.deepcopy(original))
        self.install()
        self.assertEqual(len(self.pre()), 2)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.settings(), original)
        self.assertFalse(os.path.exists(installs.manifest_path()))
        inp.assert_not_called()                              # --yes skips the question

    def test_removes_ours_from_every_recorded_file(self):
        other = tempfile.mkdtemp(prefix="ai-paladin-proj2-")
        self.install()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": other}):
            self.install()
        self.install("--user")
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0, out)
        self.assertEqual(hook.where_installed(), [])
        self.assertEqual(out.count("hook removed from"), 3)
        self.assertIn("removed from 3 file".upper(), out.upper())

    def test_a_settings_file_that_is_gone_is_not_an_error(self):
        self.install()
        os.remove(self.settings_path)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(installs.manifest_path()))

    # -- NOT a snapshot revert ------------------------------------------

    def test_hook_present_before_install_is_kept(self):
        ours = {"matcher": hook.MATCHER,
                "hooks": [{"type": "command", "command": self.our_command()}]}
        self.write_settings({"hooks": {"PreToolUse": [THIRD_PARTY, ours]}})
        out = self.install()
        self.assertIn("already in that file before this install", out)
        self.assertEqual(len(self.pre()), 2)                 # nothing duplicated
        rec = installs.load()[self.settings_path]
        self.assertEqual(rec["added"], [])
        self.assertEqual(len(rec["already_present"]), 1)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertIn("Was already present before install, keeping", out)
        self.assertNotIn("  REMOVE   ", out)
        self.assertEqual(self.pre(), [THIRD_PARTY, ours])    # untouched
        self.assertEqual(code, 0)
        self.assertIn("NO HOOK ADDED BY AI-PALADIN IS RECORDED", out)

    def test_similar_hook_from_elsewhere_is_kept_and_ours_removed(self):
        """Another AI-Paladin entry we did not write (a different checkout,
        say) is not ours to remove, even though it looks like ours."""
        stranger = {"matcher": "Bash", "hooks": [{
            "type": "command", "command": "python3 /opt/other/hooks/pre_tool_use.py"}]}
        self.write_settings({"hooks": {"PreToolUse": [stranger]}})
        self.install()
        self.assertEqual(len(self.pre()), 2)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pre(), [stranger])
        self.assertIn("Was already present before install, keeping", out)

    def test_hook_added_by_someone_else_after_install_is_kept(self):
        self.install()
        data = self.settings()
        late = {"matcher": "Edit", "hooks": [{"type": "command",
                                              "command": "added-later"}]}
        late_ai = {"matcher": "Bash", "hooks": [{
            "type": "command", "command": "python3 /srv/x/pre_tool_use.py"}]}
        data["hooks"]["PreToolUse"] += [late, late_ai]
        data["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "bye"}]}]
        self.write_settings(data)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.pre(), [late, late_ai])
        self.assertEqual(self.settings()["hooks"]["Stop"],
                         [{"hooks": [{"type": "command", "command": "bye"}]}])

    def test_reinstall_replaces_our_entry_not_others(self):
        self.write_settings({"hooks": {"PreToolUse": [THIRD_PARTY]}})
        self.install()
        self.install()
        self.assertEqual(len(self.pre()), 2)
        self.assertEqual(len(installs.load()[self.settings_path]["added"]), 1)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(self.pre(), [THIRD_PARTY])

    # -- modified entries -----------------------------------------------

    def test_modified_entry_is_flagged_and_kept(self):
        self.install()
        self.edit_our_entry(" # tweaked by hand")
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 1, out)                       # something is left to do
        self.assertIn("MODIFIED", out)
        self.assertIn("changed since install", out)
        self.assertEqual(len(self.pre()), 1)                 # not silently removed
        self.assertIn("tweaked by hand", self.pre()[0]["hooks"][0]["command"])
        self.assertIn("REMOVE THEM BY HAND", out)
        # the record stays, so a later run still knows about it
        self.assertTrue(os.path.exists(installs.manifest_path()))

    def test_modified_entry_is_flagged_at_the_prompt_and_can_be_removed(self):
        self.install()
        self.edit_our_entry(" # tweaked")
        code, out, inp, pip = self.uninstall(answers=["y", "y"])
        self.assertEqual(code, 0, out)
        self.assertIn("MODIFIED", out)
        self.assertEqual(inp.call_args_list[0].args[0], PROMPT + " ")
        self.assertIn("Remove it anyway?(y/N)", inp.call_args_list[1].args[0])
        self.assertNotIn("hooks", self.settings())
        self.assertFalse(os.path.exists(installs.manifest_path()))

    def test_modified_entry_stays_when_the_second_question_is_declined(self):
        self.install()
        self.edit_our_entry(" # tweaked")
        for second in ("n", ""):                             # default is No
            code, out, inp, pip = self.uninstall(answers=["y", second])
            self.assertEqual(code, 1)
            self.assertEqual(len(self.pre()), 1)

    def test_remove_modified_flag(self):
        self.install()
        self.edit_our_entry(" # tweaked")
        code, out, inp, pip = self.uninstall(["--yes", "--remove-modified"])
        self.assertEqual(code, 0, out)
        self.assertNotIn("hooks", self.settings())

    def test_modified_ours_is_not_confused_with_a_clean_one_in_another_file(self):
        other = tempfile.mkdtemp(prefix="ai-paladin-proj2-")
        self.install()
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": other}):
            self.install()
        self.edit_our_entry(" # tweaked")
        code, out, inp, pip = self.uninstall(["--yes"])
        gone = os.path.join(other, ".claude", "settings.local.json")
        self.assertNotIn("hooks", self.settings(gone))       # clean one removed
        self.assertEqual(len(self.pre()), 1)                 # modified one kept

    # -- after removal ---------------------------------------------------

    def test_tells_the_person_to_run_pip_uninstall_and_never_runs_it(self):
        self.install()
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0)
        pip.assert_not_called()
        self.assertIn("NEXT, RUN:  pip uninstall ai-paladin", out)
        self.assertTrue(out.rstrip().endswith("=" * 72))     # banner is last

    def test_pipx_install_is_told_to_use_pipx(self):
        self.install()
        with mock.patch.object(sys, "prefix",
                               "/home/u/.local/share/pipx/venvs/ai-paladin"), \
                mock.patch("shutil.which", return_value="/usr/bin/pipx"):
            code, out, inp, pip = self.uninstall(["--yes"])
        self.assertIn("NEXT, RUN:  pipx uninstall ai-paladin", out)

    def test_nothing_recorded(self):
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0)
        self.assertIn("NO HOOK ADDED BY AI-PALADIN IS RECORDED", out)
        self.assertIn("pip uninstall ai-paladin", out)
        inp.assert_not_called()

    # -- failure --------------------------------------------------------

    def test_unreadable_settings_file_stops_everything(self):
        self.install()
        other = tempfile.mkdtemp(prefix="ai-paladin-proj2-")
        with mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": other}):
            self.install()
        with open(self.settings_path, "w") as fh:
            fh.write("{ broken")
        good = os.path.join(other, ".claude", "settings.local.json")
        before = rd(good)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 1)
        self.assertIn("NOTHING WAS REMOVED", out)
        self.assertEqual(rd(good), before)          # nothing half-done
        self.assertNotIn("NEXT, RUN", out)

    def test_corrupt_manifest_refuses_to_guess(self):
        self.install()
        with open(installs.manifest_path(), "w") as fh:
            fh.write("not json")
        before = rd(self.settings_path)
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 1)
        self.assertIn("install_manifest.json", out)
        self.assertEqual(rd(self.settings_path), before)
        with mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(hook.main(["--install"]), 1)    # install refuses too

    def test_unknown_option(self):
        code, out, inp, pip = self.uninstall(["--nuke"])
        self.assertEqual(code, 2)

    # -- ai-paladin-hook --uninstall uses the same record ----------------

    def test_hook_uninstall_removes_only_what_we_recorded(self):
        self.write_settings({"hooks": {"PreToolUse": [THIRD_PARTY]}})
        self.install()
        with mock.patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(hook.main(["--uninstall"]), 0)
        self.assertEqual(self.pre(), [THIRD_PARTY])

    def test_hook_uninstall_without_a_record_removes_nothing(self):
        ours = {"matcher": hook.MATCHER,
                "hooks": [{"type": "command", "command": self.our_command()}]}
        self.write_settings({"hooks": {"PreToolUse": [ours]}})
        with mock.patch.object(sys, "stdout", io.StringIO()) as out:
            self.assertEqual(hook.main(["--uninstall"]), 0)
        self.assertIn("no record", out.getvalue())
        self.assertEqual(self.pre(), [ours])

    def test_hook_uninstall_keeps_a_modified_entry(self):
        self.install()
        self.edit_our_entry(" # tweaked")
        with mock.patch.object(sys, "stdout", io.StringIO()), \
                mock.patch.object(sys, "stderr", io.StringIO()) as err:
            self.assertEqual(hook.main(["--uninstall"]), 1)
        self.assertIn("edited after install", err.getvalue())
        self.assertEqual(len(self.pre()), 1)

    # -- installs from before the manifest ------------------------------

    def legacy(self, files):
        os.makedirs(self.cfg_dir, exist_ok=True)
        with open(os.path.join(self.cfg_dir, "hook_installs.json"), "w") as fh:
            json.dump({"settings_files": files}, fh)

    def old_style_entry(self):
        return {"matcher": hook.MATCHER, "hooks": [{
            "type": "command", "command": "python3 /old/place/hooks/pre_tool_use.py"}]}

    def test_install_from_an_earlier_version_is_still_removed(self):
        self.write_settings({"hooks": {"PreToolUse": [THIRD_PARTY,
                                                       self.old_style_entry()]}})
        self.legacy([self.settings_path])
        code, out, inp, pip = self.uninstall(["--yes"])
        self.assertEqual(code, 0, out)
        self.assertIn("recorded by an earlier version", out)
        self.assertEqual(self.pre(), [THIRD_PARTY])
        self.assertFalse(os.path.exists(os.path.join(self.cfg_dir,
                                                     "hook_installs.json")))

    def test_reinstall_takes_over_an_earlier_versions_entry(self):
        self.write_settings({"hooks": {"PreToolUse": [self.old_style_entry()]}})
        self.legacy([self.settings_path])
        self.install()
        self.assertEqual(len(self.pre()), 1)                 # replaced, not doubled
        self.assertNotEqual(self.pre()[0], self.old_style_entry())
        self.assertEqual(len(installs.load()[self.settings_path]["added"]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.cfg_dir,
                                                     "hook_installs.json")))


if __name__ == "__main__":
    unittest.main()
