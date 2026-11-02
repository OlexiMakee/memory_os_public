#!/usr/bin/env bash
# Start two llama-server instances for Memory OS daemon.
#
# Action server  (port 8312): base model + action_router LoRA
# Responder server (port 8313): base model + responder LoRA
#
# Usage:
#   ./scripts/start_llama_server.sh          # start both, print env vars, block
#   source <(./scripts/start_llama_server.sh --export-env)  # source env into shell
#
# Both servers bind to 127.0.0.1 only (no external exposure).
# Logs: /tmp/llama_action.log, /tmp/llama_responder.log
#
# Required env (or defaults below):
#   LLAMA_CPP_BIN              llama-server binary path
#   LLAMA_CPP_MODEL            base model GGUF path
#   LLAMA_CPP_LORA             action LoRA adapter GGUF
#   LLAMA_CPP_LORA_RESPONDER   responder LoRA adapter GGUF
#
# After starting, set in .env or export:
#   LLAMA_SERVER_URL=http://127.0.0.1:8312
#   LLAMA_SERVER_URL_RESPONDER=http://127.0.0.1:8313

set -euo pipefail

LLAMA_SERVER="${LLAMA_CPP_BIN:-/home/oleksii/dev/llama.cpp/build/bin/llama-server}"
MODEL="${LLAMA_CPP_MODEL:-/home/oleksii/models/gguf/Qwen3.5-4B-Base.Q4_K_M.gguf}"
ACTION_LORA="${LLAMA_CPP_LORA:-/home/oleksii/models/gguf/action_router_v003.gguf}"
RESPONDER_LORA="${LLAMA_CPP_LORA_RESPONDER:-/home/oleksii/models/gguf/responder_v002.gguf}"
ACTION_PORT="${LLAMA_SERVER_ACTION_PORT:-8312}"
RESPONDER_PORT="${LLAMA_SERVER_RESPONDER_PORT:-8313}"
EXPORT_ENV=0

for arg in "$@"; do
    [[ "$arg" == "--export-env" ]] && EXPORT_ENV=1
done

_die() { echo "[start_llama_server] ERROR: $*" >&2; exit 1; }
_check() { [[ -f "$1" ]] || _die "File not found: $1"; }

_check "$LLAMA_SERVER"
_check "$MODEL"
_check "$ACTION_LORA"
_check "$RESPONDER_LORA"

_kill_port() {
    local port=$1
    local pid
    pid=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        echo "[start_llama_server] Stopping existing process on :${port} (pid=$pid)"
        kill "$pid" 2>/dev/null || true
        sleep 1
    fi
}

_kill_port "$ACTION_PORT"
_kill_port "$RESPONDER_PORT"

echo "[start_llama_server] Starting action server on :${ACTION_PORT}..."
"${LLAMA_SERVER}" \
    -m "${MODEL}" \
    --lora "${ACTION_LORA}" \
    --port "${ACTION_PORT}" \
    --host 127.0.0.1 \
    -c 512 \
    -np 1 \
    -ngl 99 \
    --embeddings \
    > /tmp/llama_action.log 2>&1 &
ACTION_PID=$!

echo "[start_llama_server] Starting responder server on :${RESPONDER_PORT}..."
"${LLAMA_SERVER}" \
    -m "${MODEL}" \
    --lora "${RESPONDER_LORA}" \
    --port "${RESPONDER_PORT}" \
    --host 127.0.0.1 \
    -c 512 \
    -np 1 \
    -ngl 99 \
    --embeddings \
    > /tmp/llama_responder.log 2>&1 &
RESPONDER_PID=$!

echo "[start_llama_server] Waiting for servers to become ready..."
READY=0
for i in $(seq 1 40); do
    sleep 1
    action_ok=0; responder_ok=0
    curl -sf "http://127.0.0.1:${ACTION_PORT}/health"    > /dev/null 2>&1 && action_ok=1    || true
    curl -sf "http://127.0.0.1:${RESPONDER_PORT}/health" > /dev/null 2>&1 && responder_ok=1 || true
    if [[ $action_ok -eq 1 && $responder_ok -eq 1 ]]; then
        READY=1; break
    fi
    echo -n "."
done
echo ""

if [[ $READY -eq 0 ]]; then
    echo "[start_llama_server] ERROR: Servers not ready within 40s" >&2
    echo "  Action log:    /tmp/llama_action.log" >&2
    echo "  Responder log: /tmp/llama_responder.log" >&2
    kill "$ACTION_PID" "$RESPONDER_PID" 2>/dev/null || true
    exit 1
fi

echo "[start_llama_server] Both servers ready."
echo "  Action PID=$ACTION_PID    → http://127.0.0.1:${ACTION_PORT}"
echo "  Responder PID=$RESPONDER_PID → http://127.0.0.1:${RESPONDER_PORT}"
echo ""

if [[ $EXPORT_ENV -eq 1 ]]; then
    echo "export LLAMA_SERVER_URL=http://127.0.0.1:${ACTION_PORT}"
    echo "export LLAMA_SERVER_URL_RESPONDER=http://127.0.0.1:${RESPONDER_PORT}"
    exit 0
fi

echo "Add to .env:"
echo "  LLAMA_SERVER_URL=http://127.0.0.1:${ACTION_PORT}"
echo "  LLAMA_SERVER_URL_RESPONDER=http://127.0.0.1:${RESPONDER_PORT}"
echo ""
echo "Then start daemon: memory_os telegram-daemon --poll-interval 2"
echo ""

# Keep running to wait for background servers if started as service
wait
