#!/usr/bin/env bash
# Ubuntu-first bootstrap for a local Memory OS checkout.
#
# Default mode is intentionally conservative: it does not run apt, does not
# install Ollama, and does not pull models unless requested.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

DO_APT=0
DO_OLLAMA=0
PULL_MODEL=""
EXTRAS=""
SMOKE_UI=0
SKIP_PIP=0

usage() {
    cat <<'EOF'
Usage:
  bash scripts/bootstrap_ubuntu.sh [options]

Options:
  --apt                 Install Ubuntu system packages with apt-get.
  --ollama             Install Ollama with the official install script.
  --pull-model MODEL   Pull an Ollama model, for example llama3.2:3b.
  --extras EXTRAS      Install package extras, for example dev or providers-ollama,resource-psutil.
  --smoke-ui           Start the UI briefly and smoke-check HTTP routes.
  --skip-pip           Skip Python package installation and only run checks.
  -h, --help           Show this help.

Examples:
  bash scripts/bootstrap_ubuntu.sh
  bash scripts/bootstrap_ubuntu.sh --apt --extras dev,providers-ollama,resource-psutil
  bash scripts/bootstrap_ubuntu.sh --ollama --pull-model llama3.2:3b --extras providers-ollama
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apt)
            DO_APT=1
            shift
            ;;
        --ollama)
            DO_OLLAMA=1
            shift
            ;;
        --pull-model)
            PULL_MODEL="${2:-}"
            if [[ -z "$PULL_MODEL" ]]; then
                echo "error: --pull-model requires a model name" >&2
                exit 2
            fi
            shift 2
            ;;
        --extras)
            EXTRAS="${2:-}"
            if [[ -z "$EXTRAS" ]]; then
                echo "error: --extras requires a comma-separated extras list" >&2
                exit 2
            fi
            shift 2
            ;;
        --smoke-ui)
            SMOKE_UI=1
            shift
            ;;
        --skip-pip)
            SKIP_PIP=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

log() {
    printf '\n==> %s\n' "$1"
}

require_ubuntu() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        echo "error: this bootstrap is intended for Ubuntu/Linux, current OS is $(uname -s)" >&2
        exit 1
    fi
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        source /etc/os-release
        if [[ "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *"ubuntu"* && "${ID_LIKE:-}" != *"debian"* ]]; then
            echo "warning: detected ${PRETTY_NAME:-unknown}; continuing because it is Linux" >&2
        fi
    fi
}

run_apt() {
    log "Installing Ubuntu system packages"
    sudo apt-get update
    sudo apt-get install -y \
        ca-certificates \
        curl \
        git \
        python3 \
        python3-pip \
        python3-venv \
        sqlite3
}

install_ollama() {
    log "Installing Ollama"
    if command -v ollama >/dev/null 2>&1; then
        echo "ollama already installed: $(ollama --version)"
        return
    fi
    curl -fsSL https://ollama.com/install.sh | sh
}

setup_python() {
    log "Preparing Python virtual environment"
    cd "$ROOT_DIR"

    if [[ ! -d "$VENV_DIR" ]]; then
        if [[ "$SKIP_PIP" -eq 1 ]]; then
            echo "error: $VENV_DIR does not exist; run without --skip-pip first" >&2
            exit 1
        fi
        if command -v uv >/dev/null 2>&1; then
            uv venv --python python3 "$VENV_DIR"
        else
            python3 -m venv "$VENV_DIR"
        fi
    fi

    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    if [[ "$SKIP_PIP" -eq 0 ]]; then
        if [[ -n "$EXTRAS" ]]; then
            if command -v uv >/dev/null 2>&1; then
                uv pip install -e ".[$EXTRAS]"
            else
                python -m pip install --upgrade pip setuptools wheel
                python -m pip install -e ".[$EXTRAS]"
            fi
        else
            if command -v uv >/dev/null 2>&1; then
                uv pip install -e .
            else
                python -m pip install --upgrade pip setuptools wheel
                python -m pip install -e .
            fi
        fi
    fi
}

pull_model_if_requested() {
    if [[ -z "$PULL_MODEL" ]]; then
        return
    fi
    log "Pulling Ollama model: $PULL_MODEL"
    if ! command -v ollama >/dev/null 2>&1; then
        echo "error: ollama is not installed; use --ollama first or install it manually" >&2
        exit 1
    fi
    ollama pull "$PULL_MODEL"
}

run_memory_checks() {
    log "Running Memory OS checks"
    cd "$ROOT_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHONPATH=src python3 -m memory_os validate
    PYTHONPATH=src python3 -m memory_os doctor
    PYTHONPATH=src python3 -m memory_os adapters audit
}

smoke_ui() {
    if [[ "$SMOKE_UI" -eq 0 ]]; then
        return
    fi
    log "Smoke-checking UI on 127.0.0.1:8099"
    cd "$ROOT_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHONPATH=src python3 -m memory_os ui --port 8099 > /tmp/memory_os_ui.log 2>&1 &
    local ui_pid=$!
    trap 'kill "$ui_pid" >/dev/null 2>&1 || true' EXIT
    sleep 2
    curl -fsS http://127.0.0.1:8099/ >/dev/null
    curl -fsS http://127.0.0.1:8099/api/graph >/dev/null
    curl -fsS http://127.0.0.1:8099/api/spaces >/dev/null
    kill "$ui_pid" >/dev/null 2>&1 || true
    trap - EXIT
}

main() {
    require_ubuntu
    if [[ "$DO_APT" -eq 1 ]]; then
        run_apt
    fi
    if [[ "$DO_OLLAMA" -eq 1 ]]; then
        install_ollama
    fi
    setup_python
    pull_model_if_requested
    run_memory_checks
    smoke_ui
    log "Ubuntu bootstrap complete"
}

main "$@"
