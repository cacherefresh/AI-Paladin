"""
The rules files stay out of the keyword gate's scan under the ai-paladin/ prefix.

Run from ai-paladin/:  python3 -m unittest tests.test_protected_paths -v

router/keywords.yaml lists the rules files in `scan_exclude`: the files that
define the gate must not trip the gate, so they are never staged for egress or
content-scanned. This pins that the explicit entries use the current top-level
folder name (it was ai-org-router/ before the rename), and that each real
policy file is still excluded from the real-repo corpus.

What this proves, and what it does not: it proves the router's file scanner
skips these files by their repo-relative path. It does not prove an agent is
blocked from EDITING them - `scan_exclude` is about scanning only. Editing
is guarded separately, by the PreToolUse hook's hook-tamper rule, and only
where the hook is installed: tests/test_policy_file_guard.py.
"""

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from ai_paladin import paths                                         # noqa: E402
from ai_paladin.router import classifier                    # noqa: E402

FOLDER = "ai-paladin"
OLD_FOLDER = "ai-org-router"

EXPLICIT = [
    FOLDER + "/router/keywords.yaml",
    FOLDER + "/router/policy.yaml",
    FOLDER + "/config/keywords.yaml",
    FOLDER + "/security/policies/*.yaml",
    FOLDER + "/security/monitors/*.yaml",
]

# Real files, as the real-repo corpus (rooted at the repo) would see them.
REAL_FILES = [
    FOLDER + "/router/keywords.yaml",
    FOLDER + "/router/policy.yaml",
    FOLDER + "/config/keywords.yaml",
    FOLDER + "/security/policies/commands.yaml",
    FOLDER + "/security/policies/packages.yaml",
    FOLDER + "/security/monitors/behavioral_rules.yaml",
]


def _shipped_scan_exclude():
    kw = classifier.load_yaml(paths.shipped("router", "keywords.yaml"))
    return kw.get("scan_exclude") or []


class ScanExcludeUsesNewFolderName(unittest.TestCase):

    def test_explicit_entries_use_the_new_prefix(self):
        listed = _shipped_scan_exclude()
        for entry in EXPLICIT:
            with self.subTest(entry=entry):
                self.assertIn(entry, listed)

    def test_no_entry_names_the_old_folder(self):
        for entry in _shipped_scan_exclude():
            with self.subTest(entry=entry):
                self.assertNotIn(OLD_FOLDER, entry)

    def test_explicit_entries_alone_exclude_the_policy_files(self):
        # The `*/...` and bare-path entries would also match; strip them so
        # only the ai-paladin/ entries can be what excludes the files.
        with mock.patch.object(classifier, "_scan_exclude",
                               return_value=list(EXPLICIT)):
            for rel in REAL_FILES:
                with self.subTest(file=rel):
                    self.assertTrue(classifier.is_excluded(rel))
            # The old prefix is not excluded by the explicit entries.
            self.assertFalse(classifier.is_excluded(
                OLD_FOLDER + "/router/policy.yaml"))
            # Ordinary files are still scanned.
            self.assertFalse(classifier.is_excluded(
                FOLDER + "/ai_paladin/router/classifier.py"))


class PolicyFilesStayOutOfTheCorpus(unittest.TestCase):

    def test_real_files_exist_where_the_entries_say(self):
        repo = os.path.dirname(_ROOT)
        for rel in REAL_FILES:
            with self.subTest(file=rel):
                self.assertTrue(os.path.isfile(os.path.join(repo, rel)))

    def test_real_repo_corpus_skips_every_policy_file(self):
        # Only meaningful from a source checkout: in a wheel there is no
        # repo around the shipped folder.
        if os.path.basename(_ROOT) != FOLDER:
            self.skipTest("not a source checkout")
        corpus = classifier.CORPORA["real-repo"]
        if os.path.abspath(corpus["root"]) != os.path.dirname(_ROOT):
            self.skipTest("real-repo corpus is not the checkout root")
        files = classifier.list_corpus_files("real-repo")
        self.assertTrue(files, "the real-repo corpus should not be empty")
        for rel in REAL_FILES:
            with self.subTest(file=rel):
                self.assertNotIn(rel, files)


if __name__ == "__main__":
    unittest.main()
