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

# Opt-in: copy the reviewed sample session from logs.example/ into logs/, so
# a first-time user has records to read. A file is seeded only if it is
# missing or empty - sample records are never mixed in ahead of real ones,
# because logs/ is this machine's audit trail. Each sample file ends with a
# {"kind": "sample-end"} record; real activity appends below it.
seed_sample_logs() {
  mkdir -p logs
  local src dst
  for src in logs.example/*.jsonl; do
    dst="logs/$(basename "$src")"
    if [ -s "$dst" ]; then
      echo "sample logs: $dst already has records - left untouched"
    else
      cp "$src" "$dst"
      echo "sample logs: seeded $dst (sample ends at --sample-logfile--ends-here----)"
    fi
  done
}

CMD=start
SEED=0
for arg in "$@"; do
  case "$arg" in
    start|stop|restart) CMD="$arg" ;;
    --with-sample-logs) SEED=1 ;;
    *) echo "usage: $0 [start|stop|restart] [--with-sample-logs]"; exit 1 ;;
  esac
done

case "$CMD" in
  stop)    stop ;;
  restart) stop; [ "$SEED" = 1 ] && exec "$0" start --with-sample-logs; exec "$0" start ;;
  start)
    stop
    command -v ollama >/dev/null || { echo "ollama not found on PATH"; exit 1; }
    curl -sf -m 3 http://localhost:11434/api/tags >/dev/null \
      || { echo "ollama is not responding on :11434 - run 'ollama serve'"; exit 1; }
    mkdir -p logs
    [ "$SEED" = 1 ] && seed_sample_logs
    nohup "$PY" -u -m ai_paladin.server.app > logs/server.log 2>&1 &
    sleep 2
    curl -sf -m 3 "http://localhost:$PORT/api/health" >/dev/null \
      && echo "AI-Paladin up -> http://localhost:$PORT  ($PY)" \
      || { echo "failed to start; see logs/server.log"; tail -20 logs/server.log; exit 1; }
    ;;
  *) echo "usage: $0 [start|stop|restart] [--with-sample-logs]"; exit 1 ;;
esac
