# nodes/
One heartbeat agent runs on every machine (schemas/node.schema.json).
Reports status to the router/UI on an interval.

- heartbeat_agent.py   - reports role, model, load, current task
- ollama_worker.py     - executes local-tier tasks against the on-prem model
                         picked in the dashboard (models/catalog.yaml)
- web_tools.py         - the on-prem model's only route to the internet
- subagents.py         - sentry / clerk / engineer roster

## Internet access for the on-prem model

Set in the dashboard, default from `internet_access` in router/policy.yaml.

| Setting | What the model can do | Enforced by |
|---|---|---|
| no-external-network-io | Read files and write code on-prem. No web. | No web tools offered; worker thread sealed to loopback by `security/egress_guard.sealed_thread()` |
| read-only (default) | Search and read public pages (GET); send HTTP QUERY to APIs that support it | `web_tools.py`: method allowlist from `policy.yaml`, no cookies, public addresses only, outbound text (including a query body) through the keyword gate |
| read/write | Also write: POST, PUT, PATCH, DELETE; submit forms and sign in | As read-only, plus a per-task cookie jar and accounts bound to their domains |

### HTTP methods

Every method in the IANA HTTP Method Registry (41 entries), plus the
unregistered PURGE, is classed in `web_tools.py`:

| Class | Methods | Where it can apply |
|---|---|---|
| read (7) | GET, HEAD, OPTIONS, QUERY, PROPFIND, REPORT, SEARCH | read-only and read/write |
| write (31) | POST, PUT, PATCH, DELETE; the WebDAV family (PROPPATCH, MKCOL, COPY, MOVE, LOCK, UNLOCK, VERSION-CONTROL, CHECKOUT, CHECKIN, UNCHECKOUT, MKWORKSPACE, UPDATE, LABEL, MERGE, BASELINE-CONTROL, MKACTIVITY, ORDERPATCH, ACL, MKREDIRECTREF, UPDATEREDIRECTREF, MKCALENDAR, BIND, UNBIND, REBIND); LINK, UNLINK, PURGE | read/write only |
| never (4) | TRACE, CONNECT, PRI, `*` | nowhere - policy.yaml cannot list them |

Anything else is unknown and refused. What a setting actually sends is its
`methods` in router/policy.yaml plus any enabled toggle:

| Toggle | Methods | Default | In read-only |
|---|---|---|---|
| Header checks | HEAD, OPTIONS | off | applies |
| WebDAV | PROPFIND, REPORT, SEARCH + the 24 WebDAV writes | off | reads only |
| DELETE | DELETE | on | no effect |

Turning on a toggle that adds writes needs confirmation, and every toggle
change is written to the audit log. Toggles reset to their defaults on boot,
and `internet_access.lock` holds them there. LINK, UNLINK and PURGE have no
toggle; list one under read/write's `methods` if you need it. The model may
set only the WebDAV request headers (Depth, Destination, Overwrite,
Lock-Token, If, Timeout), one line each, through the keyword gate; a
Destination must also be a public address.

`_request()` checks the method before any connection opens. A policy that
breaks these rules fails closed, so no web session starts. "Read" is what the
method promises, not something this client can verify: a server can still
change data on a GET or QUERY.

Most restrictive wins. The sovereign posture forces no-external-network-io.
A protected-IP task is lowered from read/write to read-only. A query, URL or
form field that carries a protected term is refused, so protected IP does not
leave inside a search.

All of this is process-level, like the egress guard. It is not a host
firewall. A GET still sends its URL, and those bytes are counted as egress in
the ledger. The content gate is the keyword gate, so paraphrased IP that
matches no term is not caught.

### Sign-in accounts

Read/write sign-in uses `config/web_accounts.yaml`, which is gitignored and
written by a person:

```yaml
accounts:
  github:
    domains: [github.com]
    fields: {login: "you", password: "..."}
```

The model passes the account name to `web_submit`. It never sees the field
values, and an account is only ever sent to a host on its own domains list.
This is form-POST sign-in only. Sites that need JavaScript, a CAPTCHA or 2FA
will not work, because there is no browser here.
