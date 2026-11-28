"""
Runs tests/wheel_smoke.py (build the wheel, install it into a clean venv,
boot the router from it). Slow and needs the package index for PyYAML, so
it is skipped unless AI_PALADIN_WHEEL_TEST=1. CI sets it.

    AI_PALADIN_WHEEL_TEST=1 python3 -m unittest tests.test_wheel_install -v
"""

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


@unittest.skipUnless(os.environ.get("AI_PALADIN_WHEEL_TEST") == "1",
                     "set AI_PALADIN_WHEEL_TEST=1 to build and install the wheel")
class WheelInstallTest(unittest.TestCase):

    def test_wheel_installs_and_boots_in_a_clean_venv(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "wheel_smoke.py")],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
