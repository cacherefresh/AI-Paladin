#!/usr/bin/env bash
# Build the PDFs for the *latest* documentation in this tree, with headless
# Chrome or Chromium. Frozen version folders are never overwritten.
#
#   ./build_pdfs.sh --manual   rebuild only USER_CONFIG/latest/USER_CONFIG_MANUAL.html.
#                              This is the
#                              safe invocation: it never touches a pitch deck.
#   ./build_pdfs.sh            rebuild USER_CONFIG/latest; if PITCH_DECK/latest
#                              has no PDF yet, build one. Frozen PDFs are kept.
#                              Prefer --manual unless you intend the pitch-deck
#                              fallback.
#   ./build_pdfs.sh --all      the same as a plain run. An existing
#                              PITCH_DECK/latest PDF is still kept (a fresh
#                              print can paginate a pitch deck differently).
#   ./build_pdfs.sh PATH.html  build one HTML under latest/ (path relative to
#                              this directory). Refused if the path is not
#                              under a latest/ folder. Do not pass a
#                              PITCH_DECK path unless you mean to replace that
#                              PDF.
#
# Uses a throwaway browser profile, so your own Chrome profile is never read
# or changed. The decks are self-contained local files; printing them makes
# no network requests.
set -euo pipefail
cd "$(dirname "$0")"

BROWSER=""
CANDIDATES=(
  google-chrome
  google-chrome-stable
  chromium
  chromium-browser
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  "/Applications/Chromium.app/Contents/MacOS/Chromium"
)
for cand in "${CANDIDATES[@]}"; do
  if command -v "$cand" >/dev/null 2>&1; then
    BROWSER="$cand"
    break
  fi
  if [ -x "$cand" ]; then
    BROWSER="$cand"
    break
  fi
done
[ -n "$BROWSER" ] || { echo "need google-chrome or chromium on PATH (or the usual macOS app path)"; exit 1; }

PROFILE=$(mktemp -d)
trap 'rm -rf "$PROFILE"' EXIT

is_latest() {
  case "$1" in
    */latest/*|latest/*) return 0 ;;
    *) return 1 ;;
  esac
}

run_browser() {
  # GNU timeout is optional: macOS often does not have it.
  if command -v timeout >/dev/null 2>&1; then
    timeout 120 "$@"
  else
    "$@"
  fi
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
  # --no-sandbox: headless Chrome can refuse to start in a container
  # without a sandbox user namespace. Fine for a local file print.
  run_browser "$BROWSER" --headless=new --disable-gpu --no-first-run --no-sandbox \
    --user-data-dir="$PROFILE" --no-pdf-header-footer \
    --print-to-pdf="$PWD/$pdf" "file://$PWD/$html"
  printf '%-52s -> %s (%s pages)\n' "$html" "$pdf" \
    "$(pdfinfo "$pdf" 2>/dev/null | awk '/^Pages:/{print $2}')"
}

MANUAL=0
FILES=()
for a in "$@"; do
  case "$a" in
    --all) ;;
    --manual|--user-config) MANUAL=1 ;;
    *) FILES+=("$a") ;;
  esac
done

if [ "$MANUAL" = 1 ] && [ ${#FILES[@]} -gt 0 ]; then
  echo "refused: --manual does not take a path; it only builds USER_CONFIG/latest" >&2
  exit 1
fi

if [ ${#FILES[@]} -gt 0 ]; then
  for f in "${FILES[@]}"; do build "$f"; done
elif [ "$MANUAL" = 1 ]; then
  build USER_CONFIG/latest/USER_CONFIG_MANUAL.html
else
  build USER_CONFIG/latest/USER_CONFIG_MANUAL.html
  if [ -f PITCH_DECK/latest/PITCH_DECK.html ]; then
    if [ ! -f PITCH_DECK/latest/PITCH_DECK.pdf ]; then
      build PITCH_DECK/latest/PITCH_DECK.html
    else
      echo "PITCH_DECK/latest/PITCH_DECK.pdf kept (use --manual to skip this check; pass the HTML path only if you mean to rebuild the deck)"
    fi
  fi
fi
