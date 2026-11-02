#!/usr/bin/env bash
# Install user-level systemd units for a local Memory OS checkout.
#
# Default mode installs unit files and runs daemon-reload only. It does not
# enable or start services unless --enable or --start is passed.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT_DIR/deploy/systemd/user"
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

DO_ENABLE=0
DO_START=0
UNITS=("memory-os-ui.service" "memory-os-daemon.service" "memory-os-linux-inventory.service" "memory-os-linux-inventory.timer" "memory-os-mola.service")

usage() {
    cat <<'EOF'
Usage:
  bash scripts/install_systemd_user_services.sh [options]

Options:
  --enable        Enable services for this user.
  --start         Start services after installing them.
  --ui-only       Install only memory-os-ui.service.
  --daemon-only   Install only memory-os-daemon.service.
  --mola-only     Install only memory-os-mola.service.
  --inventory-only
                  Install only memory-os-linux-inventory service/timer.
  -h, --help      Show this help.

Examples:
  bash scripts/install_systemd_user_services.sh
  bash scripts/install_systemd_user_services.sh --enable
  bash scripts/install_systemd_user_services.sh --enable --start
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --enable)
            DO_ENABLE=1
            shift
            ;;
        --start)
            DO_START=1
            shift
            ;;
        --ui-only)
            UNITS=("memory-os-ui.service")
            shift
            ;;
        --daemon-only)
            UNITS=("memory-os-daemon.service")
            shift
            ;;
        --mola-only)
            UNITS=("memory-os-mola.service")
            shift
            ;;
        --inventory-only)
            UNITS=("memory-os-linux-inventory.service" "memory-os-linux-inventory.timer")
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

require_linux_systemd() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        echo "error: systemd user services are only supported on Linux here" >&2
        exit 1
    fi
    if ! command -v systemctl >/dev/null 2>&1; then
        echo "error: systemctl not found" >&2
        exit 1
    fi
    if [[ ! -x "$PYTHON_BIN" ]]; then
        echo "error: $PYTHON_BIN not found; create the Memory OS .venv first" >&2
        exit 1
    fi
}

render_unit() {
    local unit_name="$1"
    local template="$TEMPLATE_DIR/$unit_name.in"
    local destination="$USER_UNIT_DIR/$unit_name"

    if [[ ! -f "$template" ]]; then
        echo "error: missing template $template" >&2
        exit 1
    fi

    mkdir -p "$USER_UNIT_DIR"
    sed \
        -e "s|@@ROOT_DIR@@|$ROOT_DIR|g" \
        -e "s|@@PYTHON_BIN@@|$PYTHON_BIN|g" \
        "$template" > "$destination"
    echo "installed $destination"
}

main() {
    require_linux_systemd

    for unit in "${UNITS[@]}"; do
        render_unit "$unit"
    done

    systemctl --user daemon-reload

    if [[ "$DO_ENABLE" -eq 1 ]]; then
        systemctl --user enable "${UNITS[@]}"
    fi

    if [[ "$DO_START" -eq 1 ]]; then
        systemctl --user start "${UNITS[@]}"
    fi

    systemctl --user status "${UNITS[@]}" --no-pager || true
}

main "$@"
