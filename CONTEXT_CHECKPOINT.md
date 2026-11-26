# Memory OS — Context Checkpoint
**Saved:** 2026-06-29T18:41Z | **Commit:** `602b4b0` | **Branch:** `main`

---

## System State

| Component | Status |
|---|---|
| Tests | **108/108 ✅** |
| `memory_os validate` | **ok ✅** |
| Telegram daemon | **Running** — PID 115919 (pane 4) |
| Git | **Synced** — `origin/main == HEAD` |

**Daemon command:**
```bash
python3 -m memory_os telegram-daemon --swarm-control --swarm-watch-timeout 0
```

---

## Project Overview

**Memory OS** — агентська ОС. Надає агентам (claude, codex, agy) спільну пам'ять, координацію задач і Telegram-інтерфейс для мобільного управління.

**Root:** `/home/oleksii/dev/memory_os`  
**Package:** `src/memory_os/`  
**Tests:** `tests/`  
**Venv:** `.venv/`

---

## Architecture — Key Files

```
src/memory_os/
├── adapters/
│   ├── telegram_polling.py    ← ГОЛОВНИЙ файл змін цієї сесії (638 рядків)
│   └── telegram_adapter.py    ← HTTP wrapper для Telegram Bot API
├── toolkit/
│   ├── agent_health.py        ← health probe з tmux pane capture
│   ├── agent_comm.py          ← AgentComm.send() / inbox
│   ├── task_kernel.py         ← файловий task tracker
│   ├── workspace.py           ← tmux workspace + watch_task()
│   └── tmux_manager.py        ← TmuxManager
├── cli.py                     ← CLI entrypoint (telegram-daemon + watchdog)
├── core/config.py             ← MemoryOSConfig
└── modules/search.py          ← MemorySearcher (graph fallback)
```

**Tmux workspace:** `memory_os_workspace`

| Pane | Agent | Role |
|------|-------|------|
| 0 | claude | CLI agent (quota_exhausted станом на 18:40) |
| 1 | codex | CLI agent |
| 2 | agy | CLI agent |
| 3 | — | bash shell |
| 4 | telegram-daemon | Swarm Control Bot |

---

## Telegram Bot — Feature Set

Команди:

| Команда | Дія |
|---|---|
| `/start`, `/help` | Показує статус агентів + довідку |
| `/agy`, `/claude`, `/codex` | Переключає **сесію** — всі наступні повідомлення йдуть цьому агенту |
| `/swarm <текст>` | Авто-failover: вибирає першого здорового агента |
| `/note <текст>` | Накопичує нотатки в буфер (per chat) |
| `/search <query>` | Пошук у graph memory |
| `/status` | Стан активних задач |

**Sticky session:** `/agy` → всі наступні повідомлення (без `/`) йдуть до agy.  
**Notes buffer:** `/note X`, `/note Y`, потім `/agy зроби задачу` → агент отримує X+Y+задача.

---

## Key Architecture Decisions

### `_dispatch(chat_id, prompt, agent=None)` — unified method
Два методи (`_dispatch_with_failover` + `_dispatch_swarm_task`) злиті в один.
- `agent=None` → авто-failover по registry order
- `agent="agy"` → прямий dispatch

### Async через `threading.Thread(daemon=True)`
Health check і dispatch виконуються у фоновому потоці. Головний polling loop ніколи не блокується.

### Pane rate-limit detection
`_pane_rate_limited()` — читає tmux pane через `capture-pane -S -50` і шукає keywords. Без subprocess.

### Watchdog auto-restart (`cli.py`)
```python
while not stop[0]:
    daemon.run(...)
    # якщо виходить через max_retries → перестворює daemon і перезапускає через 5с
```
Ctrl+C → `stop[0] = True` → чистий вихід.

### Deterministic fallback
Якщо агент не відповів за 15с → `_check_and_relay_done_tasks()` запускає `orchestrator.run(prompt)` (граф-пошук) і відправляє результат у Telegram.

---

## Task Protocol (inter-agent)

Бот відправляє задачу агенту:
```
<prompt>

[SWARM COMPLETION REQUIRED]
IMPORTANT: Your STATUS_REPORT message will be sent DIRECTLY to the Telegram user.
Write it as a clean, human-readable answer to their question (in Ukrainian).
Do NOT include internal tracking info (files changed, pytest, risks) — only the answer.
On completion run: memory_os comm send --kind STATUS_REPORT --sender <agent> --task-id <id> claude "<відповідь>"
```

Агент відповідає:
```bash
memory_os comm send --kind STATUS_REPORT --sender agy --task-id task_XXXX claude "<відповідь>"
```

---

## Recent Commits (цієї сесії)

```
602b4b0  refactor(telegram): unified _dispatch(), async health check, watchdog auto-restart
cde408a  fix(telegram): prevent pane self-poisoning in rate-limit detection
906eca5  feat(telegram): slash session agent routing + quota exhaustion suggestions
262af1b  refactor(telegram): eliminate synchronous loop freezes
5796e70  feat(telegram): /note buffer + strip bot usernames from slash commands
81be8cf  feat(telegram): agent addressing via / commands (replaced @mention)
ba301e2  feat(telegram): auto-failover dispatcher
364df28  feat(health): live tmux pane capture for rate limit detection
3967650  feat(telegram): deterministic 100% reliable task fallback engine
```

---

## Known Issues

1. **`telegram_polling.py` 638 рядків** — після стабілізації розбити на `_routing.py`, `_dispatch.py`, `_relay.py`
2. **`llama-completion exited -2`** — llama_cpp не завантажується (VRAM). Граф-fallback покриває. Не критично.
3. **claude quota_exhausted** — пане 0 вичерпав ліміти. `/swarm` або `/agy`/`/codex` доступні.

---

## Next Planned Work (MOLA Roadmap)

- **M1:** Fine-tune `action_router_v003` (dataset: `agent_context/telegram_conversations.jsonl`)
- **M2:** Train `responder_v002`
- **M3:** Deploy background MOLA service

---

## How to Resume

```bash
cd /home/oleksii/dev/memory_os
source .venv/bin/activate

# Перевірити стан
PYTHONPATH=src python3 -m pytest tests/ -x -q
PYTHONPATH=src python3 -m memory_os validate

# Daemon статус
pgrep -fa "telegram-daemon"
tmux capture-pane -pt memory_os_workspace:agents.4 -S -20

# Перезапустити daemon якщо впав
tmux send-keys -t memory_os_workspace:agents.4 "python3 -m memory_os telegram-daemon --swarm-control --swarm-watch-timeout 0" Enter

# Swarm комунікація
memory_os comm inbox
memory_os feed --watch
```

---

## Agent Rules (AGENTS.md summary)

- `python3 -m pytest tests/ -x -q` після кожного edit
- STATUS_REPORT: `memory_os comm send claude "<...>" --kind STATUS_REPORT --task-id <id> --sender <agent_id>`
- Whitelist: `python3`, `pytest`, `git`, `memory_os`
- Не модифікувати файли поза `/home/oleksii/dev/memory_os`
