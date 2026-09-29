# security/
Three rings: prevent, detect, contain. All gates are deterministic
(hooks/scripts), never prompt-based — the model cannot negotiate with them.

- egress_guard.py   - the sovereign posture's enforcement layer. Refuses every
                      non-loopback destination at the socket, DNS included,
                      and fails closed: arm() will not enter the posture
                      unless a boot self-test proved the guard blocks.
                      Process-level, not host-level - see docs/ROADMAP.md #5.
- policies/         - allowlists & rules (packages, commands, network, paths)
- monitors/         - behavioral detection on the agent event stream
- sandbox.md        - node hardening: low-priv users, read-only mounts,
                      deny-by-default egress, immutable backups
