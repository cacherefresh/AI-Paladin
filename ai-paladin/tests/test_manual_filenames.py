"""
From v0.3.0 on, the configuration manual in USER_CONFIG/latest/ is
named USER_CONFIG_MANUAL.html / .pdf. Frozen earlier versions keep
USER_CONFIG_DECK.

Run from ai-paladin/:  python3 -m unittest tests.test_manual_filenames -v
"""

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_USER_CONFIG = _REPO / "ai-paladin" / "HUMAN_C_SUITE_DOCUMENTATION" / "USER_CONFIG"


class ManualFilenamesTest(unittest.TestCase):

    def test_latest_uses_user_config_manual(self):
        latest = _USER_CONFIG / "latest"
        self.assertTrue((latest / "USER_CONFIG_MANUAL.html").is_file())
        self.assertTrue((latest / "USER_CONFIG_MANUAL.pdf").is_file())
        self.assertFalse((latest / "USER_CONFIG_DECK.html").exists())
        self.assertFalse((latest / "USER_CONFIG_DECK.pdf").exists())

    def test_frozen_v0_2_keeps_user_config_deck(self):
        frozen = _USER_CONFIG / "v0.2"
        self.assertTrue((frozen / "USER_CONFIG_DECK.html").is_file())
        self.assertTrue((frozen / "USER_CONFIG_DECK.pdf").is_file())
        self.assertFalse((frozen / "USER_CONFIG_MANUAL.html").exists())
        self.assertFalse((frozen / "USER_CONFIG_MANUAL.pdf").exists())

    def test_build_script_targets_the_new_name(self):
        script = (_REPO / "ai-paladin" / "HUMAN_C_SUITE_DOCUMENTATION" /
                  "build_pdfs.sh").read_text(encoding="utf-8")
        self.assertIn("USER_CONFIG/latest/USER_CONFIG_MANUAL.html", script)
        self.assertNotIn("USER_CONFIG/latest/USER_CONFIG_DECK.html", script)


if __name__ == "__main__":
    unittest.main()
