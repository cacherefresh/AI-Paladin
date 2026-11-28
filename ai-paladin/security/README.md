# security/
Three rings: prevent, detect, contain. All gates are deterministic
(hooks/scripts), never prompt-based — the model cannot negotiate with them.

- egress_guard.py   - the sovereign posture's enforcement layer. Refuses every
                      non-loopback destination at the socket, DNS included,
                      and fails closed: arm() will not enter the posture
                      unless a boot self-test proved the guard blocks.
                      Process-level, not host-level - see docs/ROADMAP.md #5.
- policies/         - command, write-scope and package rules for a coding
                      agent. Enforced by the Claude Code PreToolUse hook
                      (ai_paladin/hook.py) once installed - hooks/README.md.
                      The on-prem model's network rules live in
                      router/policy.yaml internet_access, not here.
- monitors/         - behavioural rules, each stating on its `enforced:` line
                      whether the router, the hook, or neither enforces it
- sandbox.md        - node hardening: low-priv users, read-only mounts,
                      deny-by-default egress, immutable backups
