#!/usr/bin/env bash
# Tear down what run_demo.sh brought up: the router on $PALADIN_PORT, plus the
# Ollama daemon it depends on. Stdlib/coreutils only - no venv, no pip.
#
#   ./stop_demo.sh                 stop router + unload models + stop ollama
#   ./stop_demo.sh --keep-ollama   stop router, unload models, leave ollama up
#   ./stop_demo.sh --router-only   stop router only, touch nothing else
#
# Note: run_demo.sh does not start Ollama, it only refuses to start without it.
# Stopping it here is a convenience for reclaiming VRAM after a demo.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PALADIN_PORT:-8722}"

KEEP_OLLAMA=0
UNLOAD=1
for arg in "$@"; do
  case "$arg" in
    --keep-ollama) KEEP_OLLAMA=1 ;;
    --router-only) KEEP_OLLAMA=1; UNLOAD=0 ;;
    -h|--help) sed -n '2,10p' "$0" | cut -c3-; exit 0 ;;
    *) echo "unknown option: $arg  (see $0 --help)"; exit 1 ;;
  esac
done

# --- router -----------------------------------------------------------------
# Same discovery as run_demo.sh's stop(), with a pgrep fallback for the case
# where the process is alive but no longer holding the socket.
router_pids() {
  { ss -lptnH "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' || true
    pgrep -f "python.* -m server\.app" || true
  } | sort -u
}

pids=$(router_pids)
if [ -z "$pids" ]; then
  echo "router: not running (port $PORT free)"
else
  echo "router: stopping $(echo "$pids" | tr '\n' ' ')"
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    sleep 1
    [ -z "$(router_pids)" ] && break
  done
  leftover=$(router_pids)
  if [ -n "$leftover" ]; then
    echo "router: still up after TERM, sending KILL to $(echo "$leftover" | tr '\n' ' ')"
    kill -9 $leftover 2>/dev/null || true
    sleep 1
  fi
  [ -z "$(router_pids)" ] && echo "router: stopped" || { echo "router: FAILED to stop"; exit 1; }
fi

# --- ollama -----------------------------------------------------------------
if command -v ollama >/dev/null 2>&1; then
  # Unload resident models first: frees VRAM immediately and is the only thing
  # we can do without root when ollama runs as a system service.
  if [ "$UNLOAD" = 1 ] && curl -sf -m 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    loaded=$(ollama ps 2>/dev/null | awk 'NR>1 && NF {print $1}' || true)
    for m in $loaded; do
      echo "ollama: unloading $m"
      ollama stop "$m" >/dev/null 2>&1 || true
    done
  fi

  if [ "$KEEP_OLLAMA" = 1 ]; then
    echo "ollama: left running (--keep-ollama)"
  elif systemctl is-active --quiet ollama 2>/dev/null; then
    # Unit is Restart=always, so killing the pid just respawns it. Must be systemctl.
    if sudo -n systemctl stop ollama 2>/dev/null; then
      echo "ollama: systemd unit stopped"
    elif [ -t 0 ] && sudo systemctl stop ollama; then
      echo "ollama: systemd unit stopped"
    else
      echo "ollama: still running as a systemd service - run: sudo systemctl stop ollama"
    fi
  elif opids=$(pgrep -u "$(id -u)" -f '^.*ollama serve' || true); [ -n "$opids" ]; then
    echo "ollama: stopping $(echo "$opids" | tr '\n' ' ')"
    kill $opids 2>/dev/null || true
    sleep 2
    still=$(pgrep -u "$(id -u)" -f '^.*ollama serve' || true)
    [ -n "$still" ] && { kill -9 $still 2>/dev/null || true; sleep 1; }
    pgrep -f 'ollama serve' >/dev/null 2>&1 \
      && echo "ollama: still responding (started by another user?)" \
      || echo "ollama: stopped"
  else
    echo "ollama: not running"
  fi
fi

# --- leftovers --------------------------------------------------------------
# logs/*.jsonl and logs/server.log are demo evidence and are tracked in git;
# they are deliberately kept. Only stray nohup spill is removed.
[ -f nohup.out ] && { rm -f nohup.out; echo "cleanup: removed nohup.out"; }

echo "demo down."
