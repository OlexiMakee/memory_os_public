#!/usr/bin/env bash
set -Eeuo pipefail

# Memory OS Tmux Agent Swarm Dashboard
# Usage: scripts/tmux_swarm.sh

SESSION_NAME="memory_os_workspace"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if tmux has-session -t "${SESSION_NAME}" 2>/dev/null; then
    echo "Attaching to existing session ${SESSION_NAME}..."
    exec tmux attach-session -t "${SESSION_NAME}"
fi

echo "Creating new Agent Swarm Dashboard session: ${SESSION_NAME}..."

# 1. Create session with Window 0 named 'agents'
tmux new-session -d -s "${SESSION_NAME}" -n "agents"
tmux send-keys -t "${SESSION_NAME}:agents.0" "cd ${REPO_ROOT@Q} && source .venv/bin/activate && clear" C-m
tmux select-pane -t "${SESSION_NAME}:agents.0" -T "claude"

# Split window 0 into 4 panes for agents
tmux split-window -h -t "${SESSION_NAME}:agents.0"
tmux send-keys -t "${SESSION_NAME}:agents.1" "cd ${REPO_ROOT@Q} && source .venv/bin/activate && clear" C-m
tmux select-pane -t "${SESSION_NAME}:agents.1" -T "codex"

tmux split-window -v -t "${SESSION_NAME}:agents.0"
tmux send-keys -t "${SESSION_NAME}:agents.2" "cd ${REPO_ROOT@Q} && source .venv/bin/activate && clear" C-m
tmux select-pane -t "${SESSION_NAME}:agents.2" -T "agy"

tmux split-window -v -t "${SESSION_NAME}:agents.1"
tmux send-keys -t "${SESSION_NAME}:agents.3" "cd ${REPO_ROOT@Q} && source .venv/bin/activate && clear" C-m
tmux select-pane -t "${SESSION_NAME}:agents.3" -T "local-model"

# Enable pane borders with active agent titles
tmux set-option -t "${SESSION_NAME}" pane-border-status top
tmux set-option -t "${SESSION_NAME}" pane-border-format "#[fg=white,bg=blue,bold] #{pane_index}: #{pane_title} #[default]"

# Keybind for fast switching without breaking shell Tab completion (F2 or Ctrl-B Tab)
tmux bind-key -n F2 select-pane -t :.+
tmux bind-key Tab select-pane -t :.+

# 2. Create Window 1 named 'feed' for Live Communication Stream
tmux new-window -t "${SESSION_NAME}" -n "feed"
tmux send-keys -t "${SESSION_NAME}:feed" "cd ${REPO_ROOT@Q} && source .venv/bin/activate && python -m memory_os feed" C-m
tmux select-pane -t "${SESSION_NAME}:feed" -T "live-feed"

# Select window 0 agents as starting view
tmux select-window -t "${SESSION_NAME}:agents"
tmux select-pane -t "${SESSION_NAME}:agents.0"

echo "Agent Swarm Dashboard ready. Attaching..."
exec tmux attach-session -t "${SESSION_NAME}"
