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


def _fake_destination(self, url, what="request"):
    """No DNS in tests: 'internal' hosts stand in for loopback/LAN."""
    if "internal" in url:
        self._block(what, "resolves to a private address",
                    "web_tools#destination")
    return "example.com"


# The IANA HTTP Method Registry as fetched 2026-11-22 (last updated
# 2026-06-17): name -> safe. 41 rows, "*" included.
IANA = {
    "ACL": 0, "BASELINE-CONTROL": 0, "BIND": 0, "CHECKIN": 0, "CHECKOUT": 0,
    "CONNECT": 0, "COPY": 0, "DELETE": 0, "GET": 1, "HEAD": 1, "LABEL": 0,
    "LINK": 0, "LOCK": 0, "MERGE": 0, "MKACTIVITY": 0, "MKCALENDAR": 0,
    "MKCOL": 0, "MKREDIRECTREF": 0, "MKWORKSPACE": 0, "MOVE": 0,
    "OPTIONS": 1, "ORDERPATCH": 0, "PATCH": 0, "POST": 0, "PRI": 1,
    "PROPFIND": 1, "PROPPATCH": 0, "PUT": 0, "QUERY": 1, "REBIND": 0,
    "REPORT": 1, "SEARCH": 1, "TRACE": 1, "UNBIND": 0, "UNCHECKOUT": 0,
    "UNLINK": 0, "UNLOCK": 0, "UPDATE": 0, "UPDATEREDIRECTREF": 0,
    "VERSION-CONTROL": 0, "*": 0,
}
ALL_ON = {"head_options": True, "webdav": True, "delete": True}


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
                              _fake_destination),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def session(self, mode, cfg=None, toggles=None):
        s = web_tools.WebSession(mode, cfg or self.cfg, "t-test",
                                 toggles=toggles)
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
        s = self.session("readwrite", cfg, toggles={})   # every toggle off
        out = json.loads(s.call("web_submit", {"url": "https://example.com",
                                               "method": "PUT"}))
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


    # -- every method accounted for -------------------------------------------

    def test_registry_fully_classified(self):
        self.assertEqual(web_tools.KNOWN_METHODS, set(IANA) | {"PURGE"})
        classes = (web_tools.READ_METHODS, web_tools.WRITE_METHODS,
                   web_tools.NEVER_METHODS)
        for m in web_tools.KNOWN_METHODS:
            self.assertEqual(sum(m in c for c in classes), 1, m)
        # read == the registry's safe methods, minus the two never sent
        self.assertEqual(web_tools.READ_METHODS,
                         {m for m, safe in IANA.items() if safe}
                         - {"TRACE", "PRI"})

    def test_every_method_in_every_setting(self):
        """Walk all 42 known methods plus an unknown one through every
        setting, with toggles all off, at default, and all on."""
        for mode in ("off", "read", "readwrite"):
            for tog in ({}, None, ALL_ON):
                s = self.session(mode, toggles=tog)
                for m in sorted(web_tools.KNOWN_METHODS) + ["BREW"]:
                    allowed = m in s.methods
                    if mode == "off" or m in web_tools.NEVER_METHODS \
                            or m not in web_tools.KNOWN_METHODS:
                        self.assertFalse(allowed, (mode, tog, m))
                    if mode == "read" and m in web_tools.WRITE_METHODS:
                        self.assertFalse(allowed, (mode, tog, m))
                    if not allowed:
                        with self.assertRaises(web_tools.WebBlocked,
                                               msg=(mode, tog, m)):
                            s._request(m, "https://example.com/")
        self.assertEqual(self.session("read", toggles={}).opener.sent, [])

    def test_never_and_unknown_cannot_be_listed(self):
        for bad in (["PRI"], ["*"], ["TRACE"], ["CONNECT"], ["BREW"]):
            with self.assertRaises(ValueError, msg=bad):
                web_tools.methods_for("readwrite",
                                      self._policy_with("readwrite", bad))
        p = copy.deepcopy(self.cfg.policy)
        p["internet_access"]["method_toggles"][0]["methods"].append("TRACE")
        with self.assertRaises(ValueError):
            web_tools.methods_for("read", p)

    def test_untoggled_writes_need_the_policy_file(self):
        s = self.session("readwrite", toggles=ALL_ON)
        for m in ("LINK", "UNLINK", "PURGE"):
            self.assertNotIn(m, s.methods)
        p = self._policy_with("readwrite", ["GET", "PURGE"])
        self.assertIn("PURGE", web_tools.methods_for("readwrite", p, {}))

    # -- toggles ----------------------------------------------------------------

    def test_delete_toggle(self):
        on = self.session("readwrite")                       # default: on
        off = self.session("readwrite", toggles={"delete": False})
        self.assertIn("DELETE", on.methods)
        self.assertNotIn("DELETE", off.methods)
        out = json.loads(off.call("web_submit", {"url": "https://example.com/r",
                                                 "method": "DELETE"}))
        self.assertIn("not allowed", out["error"])
        submit = off.tools()[-1]["function"]
        self.assertNotIn("DELETE",
                         submit["parameters"]["properties"]["method"]["enum"])
        self.assertNotIn("DELETE", self.session(
            "read", toggles={"delete": True}).methods)

    def test_head_options_toggle(self):
        off = self.session("read")                           # default: off
        out = json.loads(off.call("web_fetch", {"url": "https://example.com",
                                                "method": "HEAD"}))
        self.assertIn("not allowed", out["error"])
        self.assertNotIn("method", off.tools()[1]["function"]["parameters"]
                         ["properties"])
        on = self.session("read", toggles={"head_options": True})
        for m in ("HEAD", "OPTIONS"):
            out = json.loads(on.call("web_fetch", {"url": "https://example.com",
                                                   "method": m}))
            self.assertEqual(out["method"], m)
            self.assertIn("headers", out)
        self.assertEqual([x[0] for x in on.opener.sent], ["HEAD", "OPTIONS"])

    def test_webdav_toggle_in_read_adds_reads_only(self):
        s = self.session("read", toggles={"webdav": True})
        self.assertTrue({"PROPFIND", "REPORT", "SEARCH"} <= s.methods)
        self.assertFalse(s.methods & web_tools.WRITE_METHODS)
        out = json.loads(s.call("web_query", {"url": "https://dav.example.com/",
                                              "method": "PROPFIND",
                                              "body": "<propfind/>",
                                              "headers": {"Depth": "1"}}))
        self.assertNotIn("error", out)
        out = json.loads(s.call("web_submit", {"url": "https://dav.example.com/a",
                                               "method": "MOVE"}))
        self.assertIn("BLOCKED", out["error"])

    def test_webdav_writes_in_readwrite(self):
        s = self.session("readwrite", toggles={"webdav": True})
        out = json.loads(s.call("web_submit", {
            "url": "https://dav.example.com/a", "method": "MOVE",
            "headers": {"Destination": "https://dav.example.com/b",
                        "Overwrite": "F"}}))
        self.assertNotIn("error", out)
        self.assertEqual(s.opener.sent[-1][0], "MOVE")
        out = json.loads(self.session("readwrite").call("web_submit", {
            "url": "https://dav.example.com/a", "method": "MOVE"}))
        self.assertIn("not allowed", out["error"])          # toggle off

    # -- headers the model may set --------------------------------------------

    def test_header_rules(self):
        s = self.session("readwrite", toggles=ALL_ON)
        cases = [
            ({"Authorization": "Bearer x"}, "not settable"),
            ({"Cookie": "a=b"}, "not settable"),
            ({"Depth": "1\r\nX-Evil: 1"}, "line break"),
            ({"Destination": "https://internal.corp/b"}, "private"),
            ({"Destination": "https://example.com/alpha-ip"}, "protected"),
        ]
        for hdrs, why in cases:
            out = json.loads(s.call("web_submit", {
                "url": "https://dav.example.com/a", "method": "COPY",
                "headers": hdrs}))
            self.assertIn(why, out.get("error", ""), hdrs)
        out = json.loads(s.call("web_query", {
            "url": "https://dav.example.com/", "method": "PROPFIND",
            "body": "<propfind/>", "headers": {"Depth": "infinity"}}))
        self.assertIn("infinity", out["error"])
        self.assertEqual(s.opener.sent, [])


if __name__ == "__main__":
    unittest.main()
