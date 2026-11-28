#!/usr/bin/env bash
# Build the PDFs for the *latest* documentation in this tree, with headless
# Chrome or Chromium. Frozen version folders are never overwritten.
#
#   ./build_pdfs.sh            rebuild USER_CONFIG/latest; if PITCH_DECK/latest
#                              has no PDF yet, build one. Frozen PDFs are kept.
#   ./build_pdfs.sh --all      the same. An existing PITCH_DECK/latest PDF is
#                              still kept (a fresh print can paginate a pitch
#                              deck differently).
#   ./build_pdfs.sh PATH.html  build one HTML under latest/ (path relative to
#                              this directory). Refused if the path is not
#                              under a latest/ folder.
#
# Uses a throwaway browser profile, so your own Chrome profile is never read
# or changed. The decks are self-contained local files; printing them makes
# no network requests.
set -euo pipefail
cd "$(dirname "$0")"

BROWSER=""
for cand in google-chrome google-chrome-stable chromium chromium-browser; do
  command -v "$cand" >/dev/null 2>&1 && { BROWSER="$cand"; break; }
done
[ -n "$BROWSER" ] || { echo "need google-chrome or chromium on PATH"; exit 1; }

PROFILE=$(mktemp -d)
trap 'rm -rf "$PROFILE"' EXIT

is_latest() {
  case "$1" in
    */latest/*|latest/*) return 0 ;;
    *) return 1 ;;
  esac
}

build() {
  local html="$1"
  local dir pdf
  dir=$(dirname "$html")
  pdf="${html%.html}.pdf"
  if ! is_latest "$html"; then
    echo "refused: $html is not under latest/ (frozen PDFs are not rebuilt)" >&2
    return 1
  fi
  mkdir -p "$dir"
  # timeout and --no-sandbox: headless Chrome can hang or refuse to start
  # in a container without a sandbox user namespace.
  timeout 120 "$BROWSER" --headless=new --disable-gpu --no-first-run --no-sandbox \
    --user-data-dir="$PROFILE" --no-pdf-header-footer \
    --print-to-pdf="$PWD/$pdf" "file://$PWD/$html"
  printf '%-52s -> %s (%s pages)\n' "$html" "$pdf" \
    "$(pdfinfo "$pdf" 2>/dev/null | awk '/^Pages:/{print $2}')"
}

FILES=()
for a in "$@"; do
  case "$a" in --all) ;; *) FILES+=("$a") ;; esac
done

if [ ${#FILES[@]} -gt 0 ]; then
  for f in "${FILES[@]}"; do build "$f"; done
else
  build USER_CONFIG/latest/USER_CONFIG_DECK.html
  if [ -f PITCH_DECK/latest/PITCH_DECK.html ]; then
    if [ ! -f PITCH_DECK/latest/PITCH_DECK.pdf ]; then
      build PITCH_DECK/latest/PITCH_DECK.html
    else
      echo "PITCH_DECK/latest/PITCH_DECK.pdf kept (pass the HTML path to rebuild it on purpose)"
    fi
  fi
fi
