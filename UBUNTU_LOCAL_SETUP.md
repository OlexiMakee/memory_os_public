# Ubuntu Local Setup

This is the local Ubuntu path for a copied `memory_os` checkout. It keeps the
core package local-first and makes networked or heavier installs explicit.

## A. Choose The Setup Scope

A1. Core offline setup:

```bash
bash scripts/bootstrap_ubuntu.sh
```

Use this first after file transfer. It creates `.venv` (using `uv` when
available, otherwise standard `venv`/`pip`), installs the local package in
editable mode, then runs:

```bash
PYTHONPATH=src python3 -m memory_os validate
PYTHONPATH=src python3 -m memory_os doctor
PYTHONPATH=src python3 -m memory_os adapters audit
```

A2. Ubuntu package setup:

```bash
bash scripts/bootstrap_ubuntu.sh --apt
```

This installs only the system packages Memory OS normally needs locally:
`python3`, `python3-venv`, `python3-pip`, `git`, `curl`, `ca-certificates`,
and `sqlite3`.

A3. Local LLM setup with Ollama:

```bash
bash scripts/bootstrap_ubuntu.sh --ollama --pull-model llama3.2:3b --extras providers-ollama
```

Use this only when you want LLM-backed commands such as compaction to work
without API keys. You can replace the model name with any model already chosen
for the machine.

A4. Dev setup:

```bash
bash scripts/bootstrap_ubuntu.sh --extras dev,providers-ollama,resource-psutil,validation-pydantic
```

Use this for tests and local instrumentation. Avoid `--extras all` unless the
machine is meant to test every optional adapter.

## B. Verify The Result

After setup, run:

```bash
source .venv/bin/activate
PYTHONPATH=src python3 -m memory_os validate
PYTHONPATH=src python3 -m memory_os doctor
PYTHONPATH=src python3 -m memory_os adapters audit
```

Expected baseline:

- `validate` prints `memory_os validation ok`.
- `doctor` says `ALL CRITICAL PATHS OK`.
- Optional adapters may report `available=False`; that is normal unless their
  extras were installed.

## C. UI Smoke Check

When local port binding is allowed:

```bash
bash scripts/bootstrap_ubuntu.sh --smoke-ui --skip-pip
```

Or run manually:

```bash
source .venv/bin/activate
PYTHONPATH=src python3 -m memory_os ui --port 8099
```

Then check:

```bash
curl -fsS http://127.0.0.1:8099/
curl -fsS http://127.0.0.1:8099/api/graph
curl -fsS http://127.0.0.1:8099/api/spaces
```

## D. Secrets Boundary

Do not copy `.env`, shell history, API keys, cloud credentials, or private SSH
keys into Ubuntu just to run Memory OS. For local-only operation, prefer Ollama.
If cloud providers are needed later, create a fresh `.env` inside Ubuntu and do
not commit it.

## E. User-Level systemd Services

Install user services without starting them:

```bash
bash scripts/install_systemd_user_services.sh
```

Enable them for this user:

```bash
bash scripts/install_systemd_user_services.sh --enable
```

Start them explicitly:

```bash
systemctl --user start memory-os-ui.service
systemctl --user start memory-os-daemon.service
```

Check status and logs:

```bash
systemctl --user status memory-os-ui.service memory-os-daemon.service --no-pager
journalctl --user -u memory-os-ui.service -u memory-os-daemon.service -n 100 --no-pager
```

Open the UI from a Mac through SSH tunnel:

```bash
ssh -N -L 8099:127.0.0.1:8099 oleksii@192.168.0.190
```

Then open:

```text
http://127.0.0.1:8099/
```

Known issue: the UI has opened through the tunnel and smoke routes passed, but
browser refresh can still break the page. Treat that as a separate UI bug, not
as an Ubuntu bootstrap blocker.

## F. Deferred Project Follow-Up

`News Research Automation` was copied to Ubuntu as a private, secret-bearing
checkout. Defer its environment work until the Memory OS Ubuntu setup is stable.
When returning to it, use a latest-first policy: try a clean Python 3.14
environment with `uv`, install its dependencies, then run import/test/smoke
checks. Use Python 3.12 only as a fallback if a dependency actually fails on
3.14.
