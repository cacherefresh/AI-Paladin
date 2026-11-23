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
| read-only (default) | Search and read public pages, GET only | `web_tools.py`: method allowlist, no cookies, public addresses only, outbound text through the keyword gate |
| read/write | Also submit forms and sign in | As read-only, plus a per-task cookie jar and accounts bound to their domains |

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
