"""
Shipped defaults plus the user's settings (ai_paladin/config_layers.py).

Run from ai-paladin/:  python3 -m unittest tests.test_config_layers -v

What must hold:
  * an overlay can add groups, terms and paths;
  * a shipped term is removed only by naming it - leaving it out removes
    nothing - and every removal is reported as WEAKENED;
  * a malformed overlay is refused, never half-applied;
  * policy/roster/catalog are replaced whole by a user copy;
  * the shipped defaults are small and generic, and the demo overlay restores
    the demo's terms without weakening anything.
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

from ai_paladin import config_layers, paths                  # noqa: E402
from ai_paladin.config_layers import OverlayError, merge_keywords  # noqa: E402

SHIPPED = {
    "protected_terms": [
        {"group": "credentials", "label": "Creds", "severity": "critical",
         "terms": ["password", "api key"]},
        {"group": "infrastructure", "label": "Infra", "severity": "medium",
         "terms": ["kubeconfig"]},
    ],
    "protected_paths": ["**/.env"],
}


def terms(merged, gid):
    for g in merged["protected_terms"]:
        if g["group"] == gid:
            return g["terms"]
    return None


class OverlayTests(unittest.TestCase):

    def test_empty_overlay_changes_nothing(self):
        merged, rep = merge_keywords(SHIPPED, {})
        self.assertEqual(merged, SHIPPED)
        self.assertEqual(rep["weakened"], [])

    def test_shipped_input_is_not_mutated(self):
        before = repr(SHIPPED)
        merge_keywords(SHIPPED, {"remove_terms": {"credentials": ["password"]},
                                 "add_terms": {"credentials": ["vault token"]}})
        self.assertEqual(repr(SHIPPED), before)

    def test_add_group_terms_and_paths(self):
        merged, rep = merge_keywords(SHIPPED, {
            "groups": [{"group": "projects", "severity": "critical",
                        "terms": ["project falcon"]}],
            "add_terms": {"credentials": ["vault token", "PASSWORD"]},
            "add_paths": ["**/falcon/**"],
        })
        self.assertEqual(terms(merged, "projects"), ["project falcon"])
        # case-insensitive de-duplication: PASSWORD is already there
        self.assertEqual(terms(merged, "credentials"),
                         ["password", "api key", "vault token"])
        self.assertIn("**/falcon/**", merged["protected_paths"])
        self.assertEqual(rep["weakened"], [])

    def test_removal_must_be_named_and_is_reported(self):
        merged, rep = merge_keywords(SHIPPED, {
            "remove_terms": {"credentials": ["Password"]},
            "remove_groups": ["infrastructure"],
            "remove_paths": ["**/.env"],
        })
        self.assertEqual(terms(merged, "credentials"), ["api key"])
        self.assertIsNone(terms(merged, "infrastructure"))
        self.assertEqual(merged["protected_paths"], [])
        self.assertEqual(len(rep["weakened"]), 3)
        self.assertTrue(any("password" in w.lower() for w in rep["weakened"]))

    def test_removing_something_absent_is_a_note_not_a_weakening(self):
        _, rep = merge_keywords(SHIPPED, {
            "remove_terms": {"credentials": ["not-there"], "nogroup": ["x"]},
            "remove_groups": ["nogroup"],
            "remove_paths": ["**/nope"],
        })
        self.assertEqual(rep["weakened"], [])
        self.assertEqual(len(rep["notes"]), 4)

    def test_malformed_overlays_are_refused(self):
        bad = [
            {"protected_terms": []},                         # unknown key
            {"add_terms": {"nogroup": ["x"]}},               # undefined group
            {"add_terms": {"credentials": "password"}},      # not a list
            {"groups": [{"group": "credentials", "terms": []}]},  # redefine
            {"groups": [{"group": "g", "severity": "extreme"}]},  # severity
            {"groups": [{"terms": ["x"]}]},                  # no id
            {"remove_groups": "credentials"},                # not a list
        ]
        for ov in bad:
            with self.subTest(overlay=ov):
                with self.assertRaises(OverlayError):
                    merge_keywords(SHIPPED, ov)


class FileTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ai-paladin-cfg-")
        self.patch = mock.patch.object(paths, "CONFIG_DIR", self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_no_user_files_means_shipped_everything(self):
        for name in config_layers.REPLACED_WHOLE:
            self.assertEqual(config_layers.resolve(name)[1], "shipped")
        _, rep = config_layers.load_keywords()
        self.assertEqual([s["source"] for s in rep["sources"]], ["shipped"])

    def test_user_policy_replaces_shipped_whole(self):
        self.write("policy.yaml", "defaults: {mode: sovereign}\n")
        data, src = config_layers.load_whole("policy.yaml")
        self.assertEqual(src["source"], "user")
        self.assertEqual(data, {"defaults": {"mode": "sovereign"}})

    def test_bad_overlay_file_names_the_file(self):
        self.write("keywords.yaml", "protected_terms: []\n")
        with self.assertRaises(OverlayError) as ctx:
            config_layers.load_keywords()
        self.assertIn(self.dir, str(ctx.exception))

    def test_unparseable_overlay_is_refused(self):
        self.write("keywords.yaml", "add_terms: [unclosed\n")
        with self.assertRaises(OverlayError):
            config_layers.load_keywords()

    def test_config_reload_keeps_old_rules_on_bad_overlay(self):
        from ai_paladin.router.classifier import Config
        cfg = Config()
        before = cfg.term_count()
        self.write("keywords.yaml", "nonsense: 1\n")
        with self.assertRaises(OverlayError):
            cfg.reload()
        self.assertEqual(cfg.term_count(), before)


class ShippedDefaultsTests(unittest.TestCase):
    """The real files in this repository."""

    def load(self, config_dir):
        with mock.patch.object(paths, "CONFIG_DIR", config_dir):
            return config_layers.load_keywords()

    def test_defaults_are_the_small_generic_set(self):
        merged, _ = self.load(tempfile.mkdtemp())
        self.assertEqual(
            [g["group"] for g in merged["protected_terms"]],
            ["classification-markings", "credentials", "customer-data",
             "infrastructure"])
        self.assertEqual(terms(merged, "classification-markings"),
                         ["classified", "top secret", "noforn",
                          "controlled unclassified"])

    def test_demo_overlay_adds_demo_terms_and_weakens_nothing(self):
        merged, rep = self.load(os.path.join(_ROOT, "config"))
        self.assertEqual(rep["weakened"], [])
        for t in ("nightjar", "pricing engine", "unreleased earnings"):
            self.assertTrue(any(t in g["terms"]
                                for g in merged["protected_terms"]), t)
        self.assertIn("**/alpha-ip/**", merged["protected_paths"])


if __name__ == "__main__":
    unittest.main()
