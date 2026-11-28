"""
Router HTTP API: Host, Origin, Content-Type and token checks, and
server-issued confirmation challenges (ai_paladin/server/api_guard.py).

Run from ai-org-router/:  python3 -m unittest tests.test_api_guard -v

Each test talks to a real Handler on an ephemeral loopback port. No Ollama
is needed: none of these requests reaches a model.
"""

import http.client
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.environ.setdefault("AI_PALADIN_LOG_DIR",
                      tempfile.mkdtemp(prefix="ai-paladin-test-"))
os.environ.setdefault("AI_PALADIN_CONFIG_DIR",
                      tempfile.mkdtemp(prefix="ai-paladin-cfg-"))

from ai_paladin.server import api_guard, app                # noqa: E402


class GuardUnitTests(unittest.TestCase):

    def h(self, **kw):
        base = {"Host": "127.0.0.1:8722"}
        base.update({k.replace("_", "-"): v for k, v in kw.items()})
        return base

    def test_loopback_hosts_only(self):
        for host in ("127.0.0.1:8722", "localhost:8722", "[::1]:8722"):
            api_guard.check("GET", {"Host": host}, 8722)
        for host in ("evil.example:8722", "127.0.0.1:9999", "", "localhost"):
            with self.assertRaises(api_guard.Refusal) as cm:
                api_guard.check("GET", {"Host": host}, 8722)
            self.assertEqual(cm.exception.status, 403)

    def test_foreign_origin_refused_even_for_get(self):
        with self.assertRaises(api_guard.Refusal):
            api_guard.check("GET", self.h(Origin="http://evil.example"), 8722)
        with self.assertRaises(api_guard.Refusal):
            api_guard.check("GET", self.h(Origin="null"), 8722)
        api_guard.check("GET", self.h(Origin="http://localhost:8722"), 8722)

    def test_post_needs_json_and_token(self):
        ok = self.h(Content_Type="application/json; charset=utf-8",
                    **{"X_AI_Paladin_Token": "t0k"})
        api_guard.check("POST", ok, 8722, token="t0k")
        for ctype in ("text/plain", "application/x-www-form-urlencoded",
                      "multipart/form-data", ""):
            bad = dict(ok, **{"Content-Type": ctype})
            with self.assertRaises(api_guard.Refusal) as cm:
                api_guard.check("POST", bad, 8722, token="t0k")
            self.assertEqual(cm.exception.status, 415)
        for tok in ("", "wrong"):
            bad = dict(ok, **{"X-AI-Paladin-Token": tok})
            with self.assertRaises(api_guard.Refusal) as cm:
                api_guard.check("POST", bad, 8722, token="t0k")
            self.assertEqual(cm.exception.status, 403)

    def test_challenges_are_single_use_and_bound(self):
        c = api_guard.Challenges()
        n = c.issue("change-a")
        self.assertFalse(c.consume(n, "change-b"))      # wrong change
        n = c.issue("change-a")
        self.assertTrue(c.consume(n, "change-a"))
        self.assertFalse(c.consume(n, "change-a"))      # replay
        self.assertFalse(c.consume(True, "change-a"))   # bare flag
        expired = api_guard.Challenges(ttl_s=-1)
        self.assertFalse(expired.consume(expired.issue("k"), "k"))


class LiveHandlerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.httpd.server_address[1]
        cls._old_port, app.PORT = app.PORT, cls.port
        cls.t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        app.PORT = cls._old_port

    def setUp(self):
        self._saved = dict(app._onprem)
        self._mode = app.posture_state()["mode"]

    def tearDown(self):
        with app._onprem_lock:
            app._onprem.update(self._saved)

    def req(self, method, path, body=None, headers=None, token=True,
            ctype="application/json"):
        h = {"Host": "127.0.0.1:%d" % self.port}
        if body is not None:
            h["Content-Type"] = ctype
        if token:
            h["X-AI-Paladin-Token"] = api_guard.TOKEN
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw.decode("utf-8", "replace")

    def internet(self):
        return self.req("GET", "/api/onprem", token=False)[1]["internet"]

    def test_repro_cross_origin_simple_request_is_refused(self):
        """The S4 attack: a page on another origin sends a CORS-simple
        text/plain POST. Before the fix this changed the setting."""
        before_mode, before_net = self._mode, self.internet()
        for path, body in (("/api/posture", {"mode": "superfast"}),
                           ("/api/onprem", {"internet": "readwrite",
                                            "confirm": True})):
            st, _ = self.req("POST", path, json.dumps(body).encode(),
                             headers={"Origin": "http://evil.example"},
                             token=False, ctype="text/plain")
            self.assertEqual(st, 403)
        self.assertEqual(app.posture_state()["mode"], before_mode)
        self.assertEqual(self.internet(), before_net)

    def test_dns_rebinding_host_refused(self):
        st, body = self.req("GET", "/", token=False,
                            headers={"Host": "evil.example:%d" % self.port})
        self.assertEqual(st, 403)
        self.assertNotIn(api_guard.TOKEN, json.dumps(body))

    def test_post_without_token_refused(self):
        st, _ = self.req("POST", "/api/posture", {"mode": "slow"}, token=False)
        self.assertEqual(st, 403)

    def test_readonly_get_needs_no_token(self):
        """The VS Code status bar reads GET /api/posture with no token and
        no Origin header (extension token support is deferred)."""
        st, body = self.req("GET", "/api/posture", token=False)
        self.assertEqual(st, 200)
        self.assertIn("mode", body)

    def test_dashboard_carries_the_token(self):
        st, html = self.req("GET", "/", token=False)
        self.assertEqual(st, 200)
        m = re.search(r'name="ai-paladin-token" content="([^"]+)"', html)
        self.assertTrue(m)
        self.assertEqual(m.group(1), api_guard.TOKEN)

    def test_same_origin_with_token_works(self):
        st, body = self.req("POST", "/api/onprem", {"internet": "read"},
                            headers={"Origin": "http://127.0.0.1:%d" % self.port})
        self.assertEqual(st, 200, body)
        self.assertEqual(body["internet"], "read")

    def test_bare_confirm_flag_is_not_trusted(self):
        st, body = self.req("POST", "/api/onprem",
                            {"internet": "readwrite", "confirm": True})
        self.assertEqual(st, 409)
        self.assertIn("confirm_challenge", body)
        self.assertNotEqual(self.internet(), "readwrite")

    def test_challenge_round_trip_and_binding(self):
        want = {"internet": "readwrite"}
        st, body = self.req("POST", "/api/onprem", want)
        self.assertEqual(st, 409)
        ch = body["confirm_challenge"]
        # A challenge for one change cannot confirm a different one.
        st, _ = self.req("POST", "/api/onprem",
                         {"toggles": {"webdav": True}, "confirm": ch})
        self.assertEqual(st, 409)
        st, body = self.req("POST", "/api/onprem", want)
        ch = body["confirm_challenge"]
        st, body = self.req("POST", "/api/onprem", dict(want, confirm=ch))
        self.assertEqual(st, 200, body)
        self.assertEqual(self.internet(), "readwrite")
        # Single use.
        st, _ = self.req("POST", "/api/onprem", dict(want, confirm=ch))
        self.assertEqual(st, 409)


if __name__ == "__main__":
    unittest.main()
