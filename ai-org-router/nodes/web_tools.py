"""
Internet access for the on-prem model - the only way it reaches the web.

The model never opens a socket. It asks for a tool call; this module decides
whether that call happens, and every rule below is code, not a sentence in a
system prompt. A model can be talked out of an instruction. It cannot be
talked into a method this module does not implement for its mode.

    off         no-external-network-io. Local files and code are still
                read and written on-prem; only the network leaves the
                picture. No web tools are offered, and the worker thread runs
                under security/egress_guard.sealed_thread(), so a socket to anything
                but loopback is refused before connect(). Process scope: see
                the guard's own docstring for what that does not cover.
    read        RAG research. web_search + web_fetch (GET) and web_query
                (QUERY). No cookies, no auth headers. The only request body
                is a QUERY body, which passes the keyword gate and a size cap
                like any other outbound text. The default.
    readwrite   Adds web_submit (POST, PUT, PATCH, DELETE) and a per-task
                cookie jar, so a login persists for the rest of that task.
                Sign-in uses accounts from config/web_accounts.yaml; the model
                names an account, never sees its secret values.

HTTP METHODS
    The method allowlist for each mode is `internet_access.modes[].methods`
    in router/policy.yaml, and _request() refuses any method not on it
    before a connection is opened. The YAML is the gate. Code adds a floor
    under it that no YAML edit lifts: TRACE and CONNECT are never sent, an
    unknown method is never sent, and 'read' may only list safe methods
    (GET, HEAD, OPTIONS, QUERY). A policy that breaks the floor fails closed:
    the session is not created and no web access happens.

    "Safe" is the server's declared semantics (RFC 9110; QUERY per the IETF
    httpbis QUERY method specification). A client cannot verify that a
    server keeps that promise - a GET handler can still change data. The
    method classes bound what this client asks for, not what a server does.

WHAT EVERY CALL PASSES, IN ORDER
    1. mode allows this tool and its HTTP method   (method allowlist)
    2. per-task call budget not spent      (limits.max_calls_per_task)
    3. destination is http(s), port 80/443, and every address the host
       resolves to is a public internet address - no loopback, no LAN, no
       link-local, so the model cannot use the web tools to reach this
       machine or the office network
    4. everything the MODEL wrote that would leave - query, URL, form
       fields - passes router.classifier.classify(), the same keyword gate
       that pins protected IP on-prem. A match blocks the request.

HONEST LIMITS
    * The content gate is the keyword gate. Protected IP paraphrased so that
      no term matches is not caught - the same limit the router has today.
    * Step 3 resolves the name, then urllib resolves it again to connect. A
      DNS answer that changes in between (rebinding) is not caught.
    * A GET still discloses its URL. "Read-only" means no writes, no sessions
      and no bodies; it does not mean nothing leaves. Every request's
      outbound bytes are counted as egress in the ledger.
    * Web pages are untrusted input. A page can contain instructions aimed at
      the model. The gates above hold regardless of what the model is told;
      the model's judgement is not relied on.
"""

import html
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookiejar import CookieJar

import yaml

from bus import metrics
from bus import notifications as bus
from security import egress_guard

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS_PATH = os.path.join(BASE, "config", "web_accounts.yaml")

MODES = ("off", "read", "readwrite")

# Method classes. SAFE is what 'read' may list; WRITE needs 'readwrite';
# NEVER is refused whatever policy.yaml says (TRACE echoes the request back,
# CONNECT opens a tunnel past every check below).
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "QUERY"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
NEVER_METHODS = frozenset({"TRACE", "CONNECT"})
BODY_TYPES = ("application/json", "application/x-www-form-urlencoded",
              "text/plain")
ALLOWED_PORTS = (80, 443)
# Generic client name. Never a person's name or address.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AI-Paladin-onprem/0.1"

DEFAULT_LIMITS = {
    "max_calls_per_task": 6,
    "max_response_bytes": 600_000,
    "max_result_chars": 5000,
    "max_query_chars": 300,
    "max_body_chars": 4000,
    "timeout_s": 15,
}


def methods_for(mode: str, policy: dict) -> frozenset:
    """
    The HTTP methods `mode` may send, read from policy.yaml. Fails closed:
    a missing mode entry or a method below the code floor raises, so no
    session is built from a policy this module cannot honour exactly.
    """
    if mode not in MODES:
        raise ValueError("unknown internet mode %r" % mode)
    if mode == "off":
        return frozenset()
    modes = ((policy or {}).get("internet_access") or {}).get("modes") or []
    entry = next((m for m in modes if str(m.get("id")) == mode), None)
    if entry is None:
        raise ValueError("internet mode %r has no entry in policy.yaml; "
                         "refusing to guess its methods" % mode)
    out = set()
    for raw in entry.get("methods") or []:
        m = str(raw).strip().upper()
        if m in NEVER_METHODS:
            raise ValueError("policy.yaml lists %s for %r; %s is never sent"
                             % (m, mode, m))
        if m not in SAFE_METHODS | WRITE_METHODS:
            raise ValueError("policy.yaml lists unknown method %r for %r"
                             % (raw, mode))
        if mode == "read" and m not in SAFE_METHODS:
            raise ValueError("policy.yaml lists %s for 'read'; read may only "
                             "list safe methods %s"
                             % (m, sorted(SAFE_METHODS)))
        out.add(m)
    return frozenset(out)


class WebBlocked(Exception):
    """A web request refused by policy. The message is shown to the model."""


# ---------------------------------------------------------------------------
# Tool schemas - what the model is offered, per mode
# ---------------------------------------------------------------------------

_SEARCH = {"type": "function", "function": {
    "name": "web_search",
    "description": "Search the public web. Returns titles, URLs and snippets. "
                   "Use for anything current: releases, docs, news, CVEs.",
    "parameters": {"type": "object", "required": ["query"], "properties": {
        "query": {"type": "string", "description": "search terms"}}}}}

_FETCH = {"type": "function", "function": {
    "name": "web_fetch",
    "description": "Read one public web page (HTTP GET) and return its text.",
    "parameters": {"type": "object", "required": ["url"], "properties": {
        "url": {"type": "string", "description": "http(s) URL"}}}}}

_QUERY = {"type": "function", "function": {
    "name": "web_query",
    "description": "Send an HTTP QUERY to a public API: a read-only request "
                   "whose query is in the body instead of the URL. Use it "
                   "only for APIs that document QUERY support.",
    "parameters": {"type": "object", "required": ["url", "body"],
                   "properties": {
        "url": {"type": "string", "description": "http(s) URL"},
        "body": {"type": "string", "description": "the query"},
        "content_type": {"type": "string", "enum": list(BODY_TYPES),
                         "description": "media type of body"}}}}}


def _submit_schema(write_methods) -> dict:
    methods = sorted(write_methods)
    return {"type": "function", "function": {
        "name": "web_submit",
        "description": "Write to a web endpoint (HTTP %s), e.g. submit a form "
                       "or sign in. To sign in, use POST and pass the name of "
                       "a configured account; its stored fields are added for "
                       "you and you never see them. Cookies persist for the "
                       "rest of this task." % "/".join(methods),
        "parameters": {"type": "object", "required": ["url"], "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": methods,
                       "description": "HTTP method (default POST)"},
            "fields": {"type": "object",
                       "description": "fields you write; DELETE takes none"},
            "format": {"type": "string", "enum": ["form", "json"],
                       "description": "body encoding (default form)"},
            "account": {"type": "string",
                        "description": "configured account name, for "
                                       "sign-in (POST only)"}}}}}


def tools_for(mode: str, policy: dict) -> list:
    """Tools offered to the model: only those whose method the mode allows."""
    allowed = methods_for(mode, policy)
    tools = []
    if "GET" in allowed:
        tools += [_SEARCH, _FETCH]
    if "QUERY" in allowed:
        tools.append(_QUERY)
    writes = allowed & WRITE_METHODS
    if mode == "readwrite" and writes:
        tools.append(_submit_schema(writes))
    return tools


# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5",
             "h6", "section", "article", "pre", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def html_to_text(raw: str):
    p = _Text()
    try:
        p.feed(raw)
    except Exception:
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), text


# ---------------------------------------------------------------------------
# Accounts for sign-in (readwrite only)
# ---------------------------------------------------------------------------

def load_accounts() -> dict:
    """
    config/web_accounts.yaml - gitignored, per machine, written by a person:

        accounts:
          github:
            domains: [github.com]
            fields: {login: "...", password: "..."}

    An account is only ever sent to a host on its own domains list.
    """
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except OSError:
        return {}
    return data.get("accounts", {}) or {}


def account_names() -> list:
    return sorted(load_accounts().keys())


def _host_on(host: str, domains) -> bool:
    host = (host or "").lower().rstrip(".")
    for d in domains or []:
        d = str(d).lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


# ---------------------------------------------------------------------------
# The session - one per task
# ---------------------------------------------------------------------------

class _NoPrivateRedirect(urllib.request.HTTPRedirectHandler):
    """A public page must not be able to redirect us onto the LAN."""

    def __init__(self, session):
        super().__init__()
        self.session = session

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.session._check_destination(newurl, "redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebSession:

    def __init__(self, mode: str, cfg, task_id: str, limits: dict = None,
                 search_cfg: dict = None):
        if mode not in MODES:
            raise ValueError("unknown internet mode %r" % mode)
        self.mode = mode
        self.cfg = cfg
        self.methods = methods_for(mode, getattr(cfg, "policy", None))
        self.task_id = task_id
        self.limits = dict(DEFAULT_LIMITS, **(limits or {}))
        self.search_cfg = search_cfg or {}
        self.calls = 0
        self.sources = []           # (title, url) actually read, for the UI
        self.jar = CookieJar() if mode == "readwrite" else None
        handlers = [_NoPrivateRedirect(self)]
        if self.jar is not None:
            handlers.append(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener = urllib.request.build_opener(*handlers)

    def tools(self) -> list:
        return tools_for(self.mode, getattr(self.cfg, "policy", None))

    # -- gates ---------------------------------------------------------------

    def _block(self, what: str, why: str, gate: str):
        bus.emit("policy", task_id=self.task_id, gate=gate, outcome="blocked",
                 detail="%s: %s" % (what, why))
        bus.notify("internet.blocked", "On-prem web request blocked",
                   "%s was refused. %s" % (what, why),
                   severity="warning", task_id=self.task_id, gate=gate)
        metrics.record_block()
        raise WebBlocked("%s refused: %s" % (what, why))

    def _check_mode(self, tool: str):
        if tool == "web_submit" and self.mode != "readwrite":
            self._block(tool, "internet access is '%s'; writes need readwrite"
                        % self.mode, "web_tools#method")
        if self.mode == "off":
            self._block(tool, "internet access is off (no-external-network-io)",
                        "web_tools#method")
        if egress_guard.is_armed():
            self._block(tool, "the sovereign posture is armed - no "
                        "destination outside this machine is reachable",
                        "egress_guard#sovereign")

    def _check_method(self, method: str, what: str):
        """The policy.yaml method allowlist. Runs before any connection."""
        m = (method or "").upper()
        if m in NEVER_METHODS:
            self._block(what, "%s is never sent" % m, "web_tools#method")
        if m not in self.methods:
            self._block(what, "%s is not allowed when internet access is "
                        "'%s' (allowed: %s)"
                        % (m, self.mode, ", ".join(sorted(self.methods))
                           or "none"), "web_tools#method")
        return m

    def _check_budget(self, tool: str):
        if self.calls >= int(self.limits["max_calls_per_task"]):
            self._block(tool, "per-task budget of %d web calls is spent"
                        % self.limits["max_calls_per_task"], "web_tools#budget")
        self.calls += 1

    def _check_destination(self, url: str, what: str = "request"):
        try:
            u = urllib.parse.urlsplit(url)
        except ValueError:
            self._block(what, "unparseable URL", "web_tools#destination")
        if u.scheme not in ("http", "https"):
            self._block(what, "scheme %r is not http(s)" % u.scheme,
                        "web_tools#destination")
        host = u.hostname or ""
        try:
            port = u.port or (443 if u.scheme == "https" else 80)
        except ValueError:
            self._block(what, "bad port", "web_tools#destination")
        if port not in ALLOWED_PORTS:
            self._block(what, "port %d is not 80/443" % port,
                        "web_tools#destination")
        try:
            infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, UnicodeError, egress_guard.EgressBlocked) as exc:
            self._block(what, "cannot resolve %r (%s)" % (host, exc),
                        "web_tools#destination")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
            if not ip.is_global:
                self._block(what, "%s resolves to %s, which is not a public "
                            "internet address" % (host, ip),
                            "web_tools#destination")
        return host

    def _check_content(self, text: str, what: str):
        """The protected-IP keyword gate, applied to what would leave."""
        if not text:
            return
        from router.classifier import classify
        cls = classify(text, self.cfg, staged_files=[], task_id=self.task_id)
        if cls.matched:
            terms = sorted({m.term for m in cls.matches})[:4]
            self._block(what, "it carries protected terms (%s). Protected IP "
                        "never leaves, including inside a search query or URL."
                        % ", ".join(repr(t) for t in terms),
                        "keywords.yaml#outbound")

    # -- transport -------------------------------------------------------------

    def _request(self, method: str, url: str, body: bytes = None,
                 what: str = "request",
                 content_type: str = "application/x-www-form-urlencoded"):
        method = self._check_method(method, what)
        host = self._check_destination(url, what)
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
                   "Accept-Language": "en"}
        if body is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method)
        bytes_out = len(method) + len(url) + sum(len(k) + len(v)
                                                 for k, v in headers.items())
        bytes_out += len(body or b"")
        metrics.record_web(method, bytes_out, self.task_id, host)
        bus.emit("web", task_id=self.task_id, method=method, url=url,
                 host=host, bytes_out=bytes_out, mode=self.mode,
                 node="onprem-01")
        cap = int(self.limits["max_response_bytes"])
        try:
            with self.opener.open(req, timeout=self.limits["timeout_s"]) as r:
                raw = r.read(cap)
                ctype = r.headers.get("Content-Type", "")
                final = r.geturl()
                status = r.status
        except urllib.error.HTTPError as exc:
            raw, ctype, final, status = (exc.read(cap) if exc.fp else b"",
                                         exc.headers.get("Content-Type", ""),
                                         url, exc.code)
        charset = "utf-8"
        m = re.search(r"charset=([\w-]+)", ctype or "")
        if m:
            charset = m.group(1)
        return raw.decode(charset, errors="replace"), ctype, final, status

    # -- tools -----------------------------------------------------------------

    def search(self, query: str) -> dict:
        self._check_mode("web_search")
        query = (query or "").strip()[: int(self.limits["max_query_chars"])]
        if not query:
            raise WebBlocked("empty query")
        self._check_content(query, "web_search(%r)" % query)
        self._check_budget("web_search")
        endpoint = self.search_cfg.get("endpoint",
                                       "https://lite.duckduckgo.com/lite/")
        url = endpoint + "?" + urllib.parse.urlencode({"q": query})
        raw, _, _, status = self._request("GET", url, what="web_search")
        results = _parse_ddg(raw)
        bus.notify("internet.read", "On-prem searched the web",
                   "GET %s - query %r, %d results. Read-only: no cookies, no "
                   "body." % (urllib.parse.urlsplit(endpoint).hostname, query,
                              len(results)),
                   severity="info", task_id=self.task_id)
        return {"query": query, "status": status, "results": results[:6]}

    def fetch(self, url: str) -> dict:
        self._check_mode("web_fetch")
        url = (url or "").strip()
        self._check_content(url, "web_fetch(%s)" % url)
        self._check_budget("web_fetch")
        raw, ctype, final, status = self._request("GET", url, what="web_fetch")
        if "html" in ctype or raw.lstrip()[:1] == "<":
            title, text = html_to_text(raw)
        else:
            title, text = "", raw
        cap = int(self.limits["max_result_chars"])
        self.sources.append({"title": title or final, "url": final})
        bus.notify("internet.read", "On-prem read a web page",
                   "GET %s (%d). Read-only." % (final, status),
                   severity="info", task_id=self.task_id, url=final)
        return {"url": final, "status": status, "title": title,
                "text": text[:cap], "truncated": len(text) > cap}

    def query(self, url: str, body: str, content_type: str = None) -> dict:
        """HTTP QUERY: a safe, read-only request with the query in the body."""
        self._check_mode("web_query")
        what = "web_query(%s)" % (url or "").strip()
        self._check_method("QUERY", what)
        url = (url or "").strip()
        body = body or ""
        content_type = content_type or "application/json"
        if content_type not in BODY_TYPES:
            self._block(what, "content type %r is not one of %s"
                        % (content_type, ", ".join(BODY_TYPES)),
                        "web_tools#body")
        cap = int(self.limits["max_body_chars"])
        if len(body) > cap:
            self._block(what, "body is %d chars; the cap is %d"
                        % (len(body), cap), "web_tools#body")
        # The body is model-authored outbound text: same gate as a URL.
        self._check_content(url + "\n" + body, what)
        self._check_budget("web_query")
        data = body.encode("utf-8")
        raw, ctype, final, status = self._request(
            "QUERY", url, body=data, what="web_query",
            content_type=content_type)
        title, text = html_to_text(raw) if "html" in ctype else ("", raw)
        self.sources.append({"title": title or final, "url": final})
        bus.notify("internet.read", "On-prem sent a QUERY",
                   "QUERY %s (%d body bytes) -> %d. Read-only method; the "
                   "body left and is counted as egress."
                   % (final, len(data), status),
                   severity="info", task_id=self.task_id, url=final)
        rcap = int(self.limits["max_result_chars"])
        return {"url": final, "status": status, "title": title,
                "text": text[:rcap], "truncated": len(text) > rcap}

    def submit(self, url: str, fields: dict = None, account: str = None,
               method: str = None, fmt: str = None) -> dict:
        self._check_mode("web_submit")
        method = (method or "POST").strip().upper()
        what = "web_submit(%s %s)" % (method, (url or "").strip())
        if method not in WRITE_METHODS:
            self._block(what, "%s is not a write method; web_submit sends "
                        "only %s" % (method, ", ".join(sorted(WRITE_METHODS))),
                        "web_tools#method")
        self._check_method(method, what)
        fmt = (fmt or "form").lower()
        if fmt not in ("form", "json"):
            self._block(what, "format must be form or json", "web_tools#body")
        if account and method != "POST":
            self._block(what, "account sign-in is POST only", "web_tools#method")
        if method == "DELETE" and fields:
            self._block(what, "DELETE takes no fields", "web_tools#body")
        url = (url or "").strip()
        fields = {str(k): str(v) for k, v in (fields or {}).items()}
        # Gate what the MODEL wrote. Account secrets are not model-authored,
        # never pass through the model, and are bound to their domains below.
        self._check_content(url + "\n" + json.dumps(fields), what)
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if account:
            acct = load_accounts().get(account)
            if not acct:
                raise WebBlocked("no account named %r is configured" % account)
            if not _host_on(host, acct.get("domains")):
                self._block("web_submit(%s)" % url,
                            "account %r is bound to %s, not %s"
                            % (account, acct.get("domains"), host),
                            "web_accounts#domain")
            fields.update({str(k): str(v)
                           for k, v in (acct.get("fields") or {}).items()})
        self._check_budget("web_submit")
        if method == "DELETE":
            body, ctype_out = None, None
        elif fmt == "json":
            body = json.dumps(fields).encode("utf-8")
            ctype_out = "application/json"
        else:
            body = urllib.parse.urlencode(fields).encode("utf-8")
            ctype_out = "application/x-www-form-urlencoded"
        raw, ctype, final, status = self._request(
            method, url, body=body, what="web_submit",
            content_type=ctype_out or "application/x-www-form-urlencoded")
        title, text = html_to_text(raw) if "html" in ctype else ("", raw)
        bus.notify("internet.write", "On-prem WROTE to the internet",
                   "%s %s (%d bytes, %d fields%s) -> %d. Mode readwrite."
                   % (method, url, len(body or b""), len(fields),
                      ", account '%s'" % account if account else "", status),
                   severity="critical", task_id=self.task_id, url=url,
                   account=account or "")
        # The response goes back to the model; scrub any echo of a secret.
        if account:
            for v in (load_accounts().get(account, {}).get("fields") or {}).values():
                if v and len(str(v)) >= 4:
                    text = text.replace(str(v), "[redacted]")
        cap = int(self.limits["max_result_chars"])
        return {"url": final, "status": status, "title": title,
                "text": text[:cap], "cookies": len(self.jar or [])}

    def call(self, name: str, args: dict) -> str:
        """Dispatch a model tool call. Always returns text for the model."""
        try:
            if name == "web_search":
                out = self.search(args.get("query", ""))
            elif name == "web_fetch":
                out = self.fetch(args.get("url", ""))
            elif name == "web_query":
                out = self.query(args.get("url", ""), args.get("body", ""),
                                 args.get("content_type"))
            elif name == "web_submit":
                out = self.submit(args.get("url", ""), args.get("fields"),
                                  args.get("account"), args.get("method"),
                                  args.get("format"))
            else:
                return json.dumps({"error": "unknown tool %r" % name})
            return json.dumps(out, ensure_ascii=False)
        except WebBlocked as exc:
            return json.dumps({"error": "BLOCKED BY POLICY: %s" % exc})
        except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
            return json.dumps({"error": "request failed: %s" % exc})


# ---------------------------------------------------------------------------
# DuckDuckGo HTML results
# ---------------------------------------------------------------------------

# Both DuckDuckGo front ends: /lite/ (the default - plain GET, no script
# challenge) and /html/. Each result is a link plus a snippet.
_RES_A = re.compile(r"""<a[^>]+href=["']([^"']+)["'][^>]*class=["']"""
                    r"""(?:result-link|result__a)["'][^>]*>(.*?)</a>"""
                    r"""|<a[^>]+class=["'](?:result-link|result__a)["'][^>]*"""
                    r"""href=["']([^"']+)["'][^>]*>(.*?)</a>""", re.S)
_RES_S = re.compile(r"""class=["'](?:result-snippet|result__snippet)["'][^>]*>"""
                    r"""(.*?)</(?:td|a)>""", re.S)
_TAGS = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAGS.sub("", s)).strip()


def _real_url(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
    return q.get("uddg", [href])[0]


def _parse_ddg(raw: str) -> list:
    links = [(m[0] or m[2], m[1] or m[3]) for m in _RES_A.findall(raw)]
    snippets = _RES_S.findall(raw)
    out = []
    for i, (href, title) in enumerate(links):
        url = _real_url(href)
        if "duckduckgo.com/y.js" in url:      # sponsored
            continue
        out.append({"title": _clean(title), "url": url,
                    "snippet": _clean(snippets[i]) if i < len(snippets) else ""})
    return out
