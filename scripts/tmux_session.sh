#!/usr/bin/env bash
set -Eeuo pipefail

# Usage: scripts/tmux_session.sh
# Attach to the memory_os tmux session, creating it with the repo environment.

SESSION_NAME="memory_os"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

tmux new-session -d -A -s "${SESSION_NAME}"
tmux send-keys -t "${SESSION_NAME}" "cd ${REPO_ROOT@Q} && source .venv/bin/activate" C-m
tmux attach-session -t "${SESSION_NAME}"
