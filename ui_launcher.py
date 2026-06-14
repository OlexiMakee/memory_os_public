#!/usr/bin/env python3
import sys
import os
import signal
import subprocess

# Add src to PYTHONPATH so we can run directly from root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from memory_os.core.config import MemoryOSConfig
from memory_os.ui.server import run_ui_server


def kill_existing_server(port: int) -> None:
    result = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}"],
        capture_output=True, text=True
    )
    for pid in result.stdout.strip().split():
        try:
            os.kill(int(pid), signal.SIGTERM)
            print(f"Stopped existing server (PID {pid}) on port {port}.")
        except ProcessLookupError:
            pass


def find_free_port(preferred: int) -> int:
    import socket
    kill_existing_server(preferred)
    for port in range(preferred, preferred + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port found in range {preferred}–{preferred + 9}")


def main():
    print("Initializing Memory OS UI Launcher...")

    try:
        config = MemoryOSConfig()
    except Exception as e:
        print(f"Error loading configuration: {e}")
        print("Please ensure you are running this from a valid memory_os project directory.")
        sys.exit(1)

    port = find_free_port(8080)
    run_ui_server(config, port=port)

if __name__ == "__main__":
    main()
