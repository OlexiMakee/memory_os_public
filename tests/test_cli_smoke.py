import os
import subprocess
import sys

def run_cli(*args):
    """Run a CLI command and return the CompletedProcess."""
    env = os.environ.copy()
    if "PYTHONPATH" not in env:
        # Assumes pytest is run from the project root
        env["PYTHONPATH"] = "src"
        
    cmd = [sys.executable, "-m", "memory_os"] + list(args)
    return subprocess.run(cmd, env=env, capture_output=True, text=True)

def test_cli_smoke_doctor():
    """Ensure `doctor` command runs without crashing."""
    run_cli("init")
    result = run_cli("doctor")
    assert result.returncode == 0, f"doctor failed. STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

def test_cli_smoke_ls():
    """Ensure `ls` command runs without crashing."""
    result = run_cli("ls")
    assert result.returncode == 0, f"ls failed. STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

def test_cli_smoke_search_help():
    """Ensure `search --help` command runs without crashing."""
    result = run_cli("search", "--help")
    assert result.returncode == 0, f"search --help failed. STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

def test_cli_smoke_memory_log():
    """Ensure `memory log` command runs without crashing."""
    result = run_cli("memory", "log")
    assert result.returncode == 0, f"memory log failed. STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
