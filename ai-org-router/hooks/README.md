# hooks/
Claude Code lifecycle hooks used for audit + safety.

- pre_tool_use.py   - blocks dangerous commands, logs every tool call
- session_start.py  - loads brain context into a new session
- post_tool_use.py  - writes audit.hooks_fired / security_flags back onto the task record
