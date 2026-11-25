# USER_CONFIG

The user manual for ℂacheℝefresh's AI-Paladin: how to configure it, plus the
decks that explain what it is.

| File | What it is |
|---|---|
| [USER_MANUAL/USER_CONFIG_DECK.pdf](USER_MANUAL/USER_CONFIG_DECK.pdf) | **Configuration manual.** Where settings live, every default and how to change it, the keyword overlay, postures, internet access, models, accounts, logs, commands, the Claude Code hook and how to turn it on and off, and honest limits. 16 pages. |
| [USER_MANUAL/USER_CONFIG_DECK.html](USER_MANUAL/USER_CONFIG_DECK.html) | Its source. Edit this, then rebuild the PDF. |
| [USER_MANUAL/PITCH_DECK_v0.2/](USER_MANUAL/PITCH_DECK_v0.2/) | The overview deck, v0.2: HTML, screenshots and PDF. |
| [USER_MANUAL/PITCH_DECK_v0.1/](USER_MANUAL/PITCH_DECK_v0.1/) | The overview deck, v0.1: HTML, screenshots and PDF. |
| [build_pdfs.sh](build_pdfs.sh) | Rebuilds the PDFs from their HTML with headless Chrome or Chromium. |

## Keeping it true

**The configuration manual is maintained.** Every value on its "Default
settings" slide is copied from the shipped files (`router/policy.yaml`,
`router/keywords.yaml`, `agents/roster.yaml`, `models/catalog.yaml`). When a
default changes, change the slide in the same commit, then rebuild:

```bash
./build_pdfs.sh                 # config deck, plus any deck that has no PDF yet
./build_pdfs.sh --all           # rebuild every PDF
```

**The two overview decks are snapshots.** They were written as pitch decks
before AI-Paladin became open source, and they describe the product as it was
on their date. For example, both say 37 protected terms, which was true before
the shipped defaults were cut to a small generic set. They are kept so the
manuals can grow from them. The originals stay in
`ai-org-router/HUMAN_C_SUITE_DOCUMENTATION/PITCH_DECK/`.

`PITCH_DECK_v0.1/PITCH_DECK.pdf` is the original export (29 pages);
`build_pdfs.sh` keeps it unless you pass `--all`, because a fresh print
paginates it differently.
