#!/usr/bin/env bash
# Build the PDFs in USER_MANUAL/ from their HTML sources, with headless
# Chrome/Chromium. Run after editing any deck.
#
#   ./build_pdfs.sh            build the config deck, plus any deck with no PDF yet
#   ./build_pdfs.sh --all      rebuild every PDF, replacing existing ones
#   ./build_pdfs.sh USER_CONFIG_DECK.html   build one (path under USER_MANUAL/)
#
# An existing deck PDF is kept by default: PITCH_DECK_v0.1/PITCH_DECK.pdf is
# the original export (29 pages) and a fresh print paginates differently.
#
# Uses a throwaway browser profile, so your own Chrome profile is never read
# or changed. The decks are self-contained local files; printing them makes
# no network requests.
set -euo pipefail
cd "$(dirname "$0")/USER_MANUAL"

BROWSER=""
for cand in google-chrome chromium chromium-browser; do
  command -v "$cand" >/dev/null 2>&1 && { BROWSER="$cand"; break; }
done
[ -n "$BROWSER" ] || { echo "need google-chrome or chromium on PATH"; exit 1; }

PROFILE=$(mktemp -d)
trap 'rm -rf "$PROFILE"' EXIT

build() {
  local html="$1" pdf="${1%.html}.pdf"
  "$BROWSER" --headless=new --disable-gpu --no-first-run \
    --user-data-dir="$PROFILE" --no-pdf-header-footer \
    --print-to-pdf="$PWD/$pdf" "file://$PWD/$html" >/dev/null 2>&1
  printf '%-40s -> %s (%s pages)\n' "$html" "$pdf" \
    "$(pdfinfo "$pdf" 2>/dev/null | awk '/^Pages:/{print $2}')"
}

ALL=0
FILES=()
for a in "$@"; do
  case "$a" in --all) ALL=1 ;; *) FILES+=("$a") ;; esac
done

if [ ${#FILES[@]} -gt 0 ]; then
  for f in "${FILES[@]}"; do build "$f"; done
else
  build USER_CONFIG_DECK.html
  for d in PITCH_DECK_v*/; do
    if [ "$ALL" = 1 ] || [ ! -f "${d}PITCH_DECK.pdf" ]; then
      build "${d}PITCH_DECK.html"
    else
      echo "${d}PITCH_DECK.pdf kept (use --all to rebuild)"
    fi
  done
fi
