"""
HTTP method allowlist for the on-prem model's web tools.

Run from ai-org-router/:  python3 -m unittest tests.test_web_methods -v

No network: the destination check and the opener are stubbed, and the
notification bus is patched so the tracked logs/ files are not written.
"""

import copy
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodes import web_tools                       # noqa: E402
from router.classifier import Config              # noqa: E402


class _Resp:
    def __init__(self, url):
        self.url, self.status = url, 200
        self.headers = {"Content-Type": "application/json"}

    def read(self, n):
        return b'{"ok": true}'

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self):
        self.sent = []

    def open(self, req, timeout=None):
        self.sent.append((req.get_method(), req.full_url, req.data))
        return _Resp(req.full_url)


class MethodTests(unittest.TestCase):

    def setUp(self):
        self.cfg = Config()
        self.patches = [
            mock.patch.object(web_tools.bus, "notify"),
            mock.patch.object(web_tools.bus, "emit"),
            mock.patch.object(web_tools.metrics, "record_web"),
            mock.patch.object(web_tools.metrics, "record_block"),
            mock.patch.object(web_tools.egress_guard, "is_armed",
                              return_value=False),
            mock.patch.object(web_tools.WebSession, "_check_destination",
                              lambda self, url, what="request": "example.com"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def session(self, mode, cfg=None):
        s = web_tools.WebSession(mode, cfg or self.cfg, "t-test")
        s.opener = _Opener()
        return s

    # -- policy.yaml is the allowlist ----------------------------------------

    def test_policy_methods(self):
        p = self.cfg.policy
        self.assertEqual(web_tools.methods_for("off", p), frozenset())
        self.assertEqual(web_tools.methods_for("read", p),
                         frozenset({"GET", "QUERY"}))
        self.assertEqual(web_tools.methods_for("readwrite", p),
                         frozenset({"GET", "QUERY", "POST", "PUT", "PATCH",
                                    "DELETE"}))

    def test_read_refuses_every_write_method(self):
        s = self.session("read")
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            with self.assertRaises(web_tools.WebBlocked, msg=m):
                s._request(m, "https://example.com/x", body=b"a=1")
        self.assertEqual(s.opener.sent, [])

    def test_read_submit_tool_refused(self):
        s = self.session("read")
        for m in ("POST", "PUT", "PATCH", "DELETE"):
            out = json.loads(s.call("web_submit", {"url": "https://example.com",
                                                   "method": m}))
            self.assertIn("BLOCKED BY POLICY", out["error"])
        self.assertEqual(s.opener.sent, [])

    def test_never_methods_refused_even_in_readwrite(self):
        s = self.session("readwrite")
        for m in ("TRACE", "CONNECT", "BREW"):
            with self.assertRaises(web_tools.WebBlocked, msg=m):
                s._request(m, "https://example.com/")
        self.assertEqual(s.opener.sent, [])

    def test_off_refuses_everything(self):
        s = self.session("off")
        for tool, args in (("web_fetch", {"url": "https://example.com"}),
                           ("web_query", {"url": "https://example.com",
                                          "body": "{}"})):
            self.assertIn("BLOCKED", json.loads(s.call(tool, args))["error"])
        self.assertEqual(s.opener.sent, [])
        self.assertEqual(s.tools(), [])

    # -- QUERY ----------------------------------------------------------------

    def test_query_allowed_in_read_with_body(self):
        s = self.session("read")
        out = json.loads(s.call("web_query", {"url": "https://example.com/q",
                                              "body": '{"q": "weather"}'}))
        self.assertNotIn("error", out)
        self.assertEqual(s.opener.sent,
                         [("QUERY", "https://example.com/q",
                           b'{"q": "weather"}')])

    def test_query_body_passes_keyword_gate(self):
        s = self.session("read")
        out = json.loads(s.call("web_query", {"url": "https://example.com/q",
                                              "body": "send the alpha-ip"}))
        self.assertIn("protected terms", out["error"])
        self.assertEqual(s.opener.sent, [])

    def test_query_body_size_cap(self):
        s = self.session("read")
        big = "x" * (int(s.limits["max_body_chars"]) + 1)
        out = json.loads(s.call("web_query", {"url": "https://example.com/q",
                                              "body": big}))
        self.assertIn("cap", out["error"])
        self.assertEqual(s.opener.sent, [])

    # -- readwrite writes -----------------------------------------------------

    def test_readwrite_sends_each_write_method(self):
        s = self.session("readwrite")
        for m in ("POST", "PUT", "PATCH"):
            out = json.loads(s.call("web_submit", {"url": "https://example.com",
                                                   "method": m,
                                                   "fields": {"a": "1"},
                                                   "format": "json"}))
            self.assertNotIn("error", out, m)
        out = json.loads(s.call("web_submit", {"url": "https://example.com/r",
                                               "method": "DELETE"}))
        self.assertNotIn("error", out)
        self.assertEqual([x[0] for x in s.opener.sent],
                         ["POST", "PUT", "PATCH", "DELETE"])
        self.assertIsNone(s.opener.sent[-1][2])

    def test_submit_refuses_safe_method(self):
        s = self.session("readwrite")
        out = json.loads(s.call("web_submit", {"url": "https://example.com",
                                               "method": "GET"}))
        self.assertIn("not a write method", out["error"])

    # -- tools follow the allowlist -------------------------------------------

    def test_tools_follow_policy(self):
        names = lambda mode: [t["function"]["name"]
                              for t in self.session(mode).tools()]
        self.assertEqual(names("read"), ["web_search", "web_fetch", "web_query"])
        self.assertEqual(names("readwrite"),
                         ["web_search", "web_fetch", "web_query", "web_submit"])
        submit = self.session("readwrite").tools()[-1]["function"]
        self.assertEqual(submit["parameters"]["properties"]["method"]["enum"],
                         ["DELETE", "PATCH", "POST", "PUT"])

    def test_narrowed_policy_narrows_methods(self):
        cfg = copy.copy(self.cfg)
        cfg.policy = copy.deepcopy(self.cfg.policy)
        for m in cfg.policy["internet_access"]["modes"]:
            if m["id"] == "readwrite":
                m["methods"] = ["GET", "POST"]
        s = self.session("readwrite", cfg)
        out = json.loads(s.call("web_submit", {"url": "https://example.com",
                                               "method": "DELETE"}))
        self.assertIn("not allowed", out["error"])
        self.assertEqual(s.opener.sent, [])

    # -- the floor under the YAML fails closed --------------------------------

    def _policy_with(self, mode, methods):
        p = copy.deepcopy(self.cfg.policy)
        for m in p["internet_access"]["modes"]:
            if m["id"] == mode:
                m["methods"] = methods
        return p

    def test_floor_fails_closed(self):
        bad = [("read", ["GET", "POST"]), ("read", ["DELETE"]),
               ("readwrite", ["GET", "TRACE"]), ("readwrite", ["CONNECT"]),
               ("read", ["FETCH"])]
        for mode, methods in bad:
            with self.assertRaises(ValueError, msg=(mode, methods)):
                web_tools.methods_for(mode, self._policy_with(mode, methods))

    def test_missing_mode_entry_fails_closed(self):
        p = copy.deepcopy(self.cfg.policy)
        p["internet_access"]["modes"] = [m for m in p["internet_access"]["modes"]
                                         if m["id"] != "read"]
        with self.assertRaises(ValueError):
            web_tools.methods_for("read", p)


if __name__ == "__main__":
    unittest.main()
