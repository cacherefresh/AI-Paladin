# USER_CONFIG

The configuration manual and the pitch decks now live in one place, with
exactly one copy of each version:

[ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/)

| | Current (`latest/`) | Frozen prior versions |
|---|---|---|
| Configuration manual | [USER_CONFIG_MANUAL.pdf](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/latest/USER_CONFIG_MANUAL.pdf) (v0.3.0; source [USER_CONFIG_MANUAL.html](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/latest/USER_CONFIG_MANUAL.html)) | [v0.2/](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/USER_CONFIG/v0.2/) (still named `USER_CONFIG_DECK`) |
| Pitch deck | [PITCH_DECK/latest/](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/PITCH_DECK/latest/) (v0.2; there is no v0.3 deck yet) | [v0.1/](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/PITCH_DECK/v0.1/) |

Rebuild the configuration manual PDF with
[build_pdfs.sh --manual](../ai-paladin/HUMAN_C_SUITE_DOCUMENTATION/build_pdfs.sh).
That invocation does not touch a pitch deck. Frozen PDFs are not overwritten.

Versioning rules are in [AGENTS.md](../AGENTS.md).
