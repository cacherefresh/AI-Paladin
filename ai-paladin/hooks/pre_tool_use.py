#!/usr/bin/env python3
"""
Claude Code PreToolUse hook - runnable by path, without installing.

Point Claude Code at this file (hooks/README.md). It locates the ai_paladin
package next to it and runs ai_paladin.hook; with AI-Paladin installed, the
`ai-paladin-hook` command does the same.

It does not need the AI-Paladin router to be running: Claude Code starts it
fresh for every tool call, and it reads the policy files from disk.

Claude Code blocks a call only on exit code 2; any other failure is treated
as a warning and the call goes ahead. So even a failure to load AI-Paladin
itself (moved folder, missing PyYAML, broken install) exits 2 here.
"""

import os
import sys

try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ai_paladin.hook import main
except BaseException as exc:                      # fail closed, even here
    print("AI-Paladin hook could not load (%s: %s) - refusing the call rather "
          "than letting it through unchecked." % (type(exc).__name__, exc),
          file=sys.stderr)
    sys.exit(2)

sys.exit(main())
