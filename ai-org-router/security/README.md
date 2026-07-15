# security/
Three rings: prevent, detect, contain. All gates are deterministic
(hooks/scripts), never prompt-based — the model cannot negotiate with them.

- policies/         - allowlists & rules (packages, commands, network, paths)
- monitors/         - behavioral detection on the agent event stream
- sandbox.md        - node hardening: low-priv users, read-only mounts,
                      deny-by-default egress, immutable backups
