#!/usr/bin/env bash
# Universal Bootstrapper for Memory OS Workspace
# This script ensures the portable workspace is properly initialized on a new host.

set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$WORKSPACE_DIR/venv_auto"

cd "$WORKSPACE_DIR"

if [ ! -d "$VENV_DIR" ]; then
    echo "🤖 Bootstrap: Virtual environment 'venv_auto' not found. Creating one..."
    python3 -m venv "$VENV_DIR"
    echo "🤖 Bootstrap: Installing dependencies from pyproject.toml..."
    source "$VENV_DIR/bin/activate"
    pip install -e .
else
    source "$VENV_DIR/bin/activate"
fi

if [ $# -eq 0 ]; then
    echo "🤖 Bootstrap: No command provided. Defaulting to 'python3 ui_launcher.py'."
    python3 ui_launcher.py
else
    echo "🤖 Bootstrap: Executing: $@"
    exec "$@"
fi
