# Node hardening baseline
- Worker agents run as dedicated low-privilege user (no sudo).
- Task workspace is the ONLY writable mount; everything else read-only.
- Egress deny-by-default (see policies/commands.yaml network block).
- Obsidian vault + repos: versioned, with periodic immutable (append-only)
  backups on a machine agents cannot reach. Recovery drill documented in
  brain/obsidian-vault/runbooks/.
- Subagents get scoped tools via Claude Code's native tools/disallowedTools
  frontmatter (e.g. researcher = Read/Grep/Glob only, no Write/Edit/Bash).
- Every hook decision (allow/block) is itself an event -> audit trail.
