#!/usr/bin/env bash
# AI-Paladin router demo. Stdlib Python only - no venv, no pip, no build.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PALADIN_PORT:-8722}"

# Pick an interpreter that can import the deps. A shell-activated .venv can
# shadow system python3 with an empty environment; do not trust $PATH alone.
PY=""
for cand in "${PALADIN_PYTHON:-}" python3 /usr/bin/python3 /usr/bin/python3.12; do
  [ -n "$cand" ] || continue
  command -v "$cand" >/dev/null 2>&1 || continue
  if "$cand" -c "import yaml" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "no python3 with PyYAML found. Install it:  sudo apt install python3-yaml"
  exit 1
fi

stop() {
  local pids
  pids=$(ss -lptnH "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u || true)
  [ -n "$pids" ] && { echo "stopping $pids"; kill $pids 2>/dev/null || true; sleep 1; }
  return 0
}

case "${1:-start}" in
  stop)    stop ;;
  restart) stop; exec "$0" start ;;
  start)
    stop
    command -v ollama >/dev/null || { echo "ollama not found on PATH"; exit 1; }
    curl -sf -m 3 http://localhost:11434/api/tags >/dev/null \
      || { echo "ollama is not responding on :11434 - run 'ollama serve'"; exit 1; }
    mkdir -p logs
    nohup "$PY" -u -m server.app > logs/server.log 2>&1 &
    sleep 2
    curl -sf -m 3 "http://localhost:$PORT/api/health" >/dev/null \
      && echo "AI-Paladin up -> http://localhost:$PORT  ($PY)" \
      || { echo "failed to start; see logs/server.log"; tail -20 logs/server.log; exit 1; }
    ;;
  *) echo "usage: $0 [start|stop|restart]"; exit 1 ;;
esac
