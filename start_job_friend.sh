#!/usr/bin/env bash
# Start Job-Friend: LM Studio server + models, FastAPI backend, SvelteKit frontend.
# Usage:  ./start_job_friend.sh        (Ctrl+C stops backend and frontend; LM Studio is left running)
#         ./start_job_friend.sh stop   (also unloads the models and stops the LM Studio server)
#
# EDIT THE SETTINGS BELOW to match your machine. Run `lms ls` to see the exact model names.

set -u

# ---------- settings ----------
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")" && pwd)}"     # folder that contains backend/ and frontend/
BACKEND_DIR="$REPO_DIR/backend"
FRONTEND_DIR="$REPO_DIR/frontend"
VENV_ACTIVATE="$BACKEND_DIR/.venv/bin/activate"              # set to "" if you do not use a venv

LLM_MODEL="qwen/qwen3-8b"                                    # chat model (as printed by `lms ls`)
EMBED_MODEL="text-embedding-nomic-embed-text-v2-moe"         # embedding model (as printed by `lms ls`)
LLM_CONTEXT="${LLM_CONTEXT:-8192}"                           # context length for the chat model

LMS_PORT=1234
BACKEND_PORT=8001
FRONTEND_PORT=5500
FRONTEND_MODE="dev"                                          # dev = npm run dev, none = do not start a frontend

LOG_DIR="$REPO_DIR/logs"
# ------------------------------

mkdir -p "$LOG_DIR"
say() { printf '\n== %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v lms >/dev/null 2>&1 || die "The LM Studio CLI 'lms' was not found. Install it from LM Studio (Settings > Developer) or run: ~/.lmstudio/bin/lms bootstrap"

if [ "${1:-}" = "stop" ]; then
  say "Stopping"
  lms unload --all 2>/dev/null
  lms server stop 2>/dev/null
  pkill -f "uvicorn app.main:app" 2>/dev/null
  pkill -f "vite" 2>/dev/null
  echo "Stopped."
  exit 0
fi

wait_for() {  # wait_for <url> <seconds> <label>
  local url="$1" secs="$2" label="$3" i=0
  while [ "$i" -lt "$secs" ]; do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then echo "$label is up."; return 0; fi
    sleep 1; i=$((i + 1))
  done
  return 1
}

# ---------- LM Studio ----------
say "LM Studio server"
if curl -fsS -o /dev/null "http://localhost:$LMS_PORT/v1/models" 2>/dev/null; then
  echo "Server already running on port $LMS_PORT."
else
  lms server start --port "$LMS_PORT" >"$LOG_DIR/lmstudio.log" 2>&1
  wait_for "http://localhost:$LMS_PORT/v1/models" 30 "LM Studio server" \
    || die "LM Studio server did not come up. See $LOG_DIR/lmstudio.log"
fi

say "Models"
LOADED="$(lms ps 2>/dev/null)"
if echo "$LOADED" | grep -qi "$LLM_MODEL"; then
  echo "$LLM_MODEL already loaded."
else
  echo "Loading $LLM_MODEL (this can take a minute)..."
  lms load "$LLM_MODEL" --context-length "$LLM_CONTEXT" -y || die "Could not load $LLM_MODEL. Check the name with: lms ls"
fi
if echo "$LOADED" | grep -qi "$EMBED_MODEL"; then
  echo "$EMBED_MODEL already loaded."
else
  echo "Loading $EMBED_MODEL..."
  lms load "$EMBED_MODEL" -y || die "Could not load $EMBED_MODEL. Check the name with: lms ls"
fi

# ---------- Backend ----------
say "Backend (FastAPI)"
[ -d "$BACKEND_DIR" ] || die "Backend folder not found: $BACKEND_DIR"
if curl -fsS -o /dev/null "http://localhost:$BACKEND_PORT/docs" 2>/dev/null; then
  echo "Something already answers on port $BACKEND_PORT; not starting another backend."
else
  (
    cd "$BACKEND_DIR" || exit 1
    [ -n "$VENV_ACTIVATE" ] && [ -f "$VENV_ACTIVATE" ] && . "$VENV_ACTIVATE"
    exec uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
  ) >"$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
  wait_for "http://localhost:$BACKEND_PORT/docs" 40 "Backend" \
    || die "Backend did not come up. See $LOG_DIR/backend.log"
fi

# ---------- Frontend ----------
if [ "$FRONTEND_MODE" = "dev" ]; then
  say "Frontend (SvelteKit)"
  [ -d "$FRONTEND_DIR" ] || die "Frontend folder not found: $FRONTEND_DIR"
  if curl -fsS -o /dev/null "http://localhost:$FRONTEND_PORT" 2>/dev/null; then
    echo "Something already answers on port $FRONTEND_PORT; not starting another frontend."
  else
    (
      cd "$FRONTEND_DIR" || exit 1
      exec npm run dev -- --port "$FRONTEND_PORT"
    ) >"$LOG_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    wait_for "http://localhost:$FRONTEND_PORT" 40 "Frontend" \
      || die "Frontend did not come up. See $LOG_DIR/frontend.log"
  fi
fi

say "Ready"
echo "App:      http://localhost:$FRONTEND_PORT"
echo "Backend:  http://localhost:$BACKEND_PORT/docs"
echo "Logs:     $LOG_DIR"
echo "Press Ctrl+C to stop the backend and frontend (LM Studio keeps running; use '$0 stop' to stop it too)."

cleanup() {
  echo; echo "Shutting down..."
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM
wait
