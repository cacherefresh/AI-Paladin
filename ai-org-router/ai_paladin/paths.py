"""
Where AI-Paladin's files live.

BASE is the project folder (ai-org-router/), which holds the code package
(ai_paladin/) alongside the data it reads: the gate files in router/ and
security/, agents/roster.yaml, models/catalog.yaml, config/, logs/ and ui/.

Every module locates those files through BASE instead of counting parent
folders from its own position, so moving a module cannot silently point it
at the wrong policy file.
"""

import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
