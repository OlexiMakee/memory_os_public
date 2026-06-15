#!/usr/bin/env bash
# Universal bootstrapper for Memory OS workspace.
# Creates venv_auto if missing, installs dependencies, then runs the given command
# (or starts the UI by default).

set -e

WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$WORKSPACE_DIR/venv_auto"

cd "$WORKSPACE_DIR"

if [ ! -d "$VENV_DIR" ]; then
    echo "Bootstrap: creating virtual environment 'venv_auto'..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    echo "Bootstrap: installing dependencies from pyproject.toml..."
    pip install -e .
else
    source "$VENV_DIR/bin/activate"
fi

if [ $# -eq 0 ]; then
    echo "Bootstrap: no command given, starting UI..."
    python3 ui_launcher.py
else
    exec "$@"
fi
