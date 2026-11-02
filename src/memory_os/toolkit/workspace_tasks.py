"""Task delivery and completion relay for Memory OS workspaces."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from memory_os.toolkit.agent_registry import load_agent_registry


COMPLETION_PROTOCOL = """\

[SWARM COMPLETION PROTOCOL]
По завершенню задачі обов'язково виконай у терміналі:
  memory_os comm send --kind STATUS_REPORT --sender <agent_id> --task-id {task_id} claude "<коротко: що зроблено, які файли змінено, результат pytest>"

Це автоматично:
  1. Записує agent_context/done/{task_id}.json (done-сигнал для watch_task)
  2. Додає подію в agent_context/task_events.jsonl (видно у feed --watch)
  3. Доставляє повідомлення через активний transport (file/tmux/auto)
[END PROTOCOL]"""


def send_task(
    agent_id: str,
    task_id: str,
    prompt: str,
    sender: str = "claude",
    session: Optional[str] = None,
    root: Optional[Path] = None,
    effort: str = "",
) -> bool:
    """Send a task through the configured AgentComm transport."""
    from memory_os.core.config import MemoryOSConfig
    from memory_os.toolkit.agent_comm import AgentComm
    from memory_os.toolkit.quantizer import effort_directive

    cfg = MemoryOSConfig(str((root or Path.cwd()) / "memory_os.config.json")) if root else MemoryOSConfig()
    active_root = Path(getattr(cfg, "root_dir", root or Path.cwd()))
    active_session = session or cfg.tmux_session_name
    pane_idx = {**cfg.agent_panes, "local": 3}.get(agent_id)
    if pane_idx is None:
        return False
    target = _agent_tmux_target(active_root, agent_id) or f"{active_session}:agents.{pane_idx}"
    full_message = (
        f"[TASK {task_id}]\n{effort_directive(prompt, effort)}\n{prompt}"
        + COMPLETION_PROTOCOL.format(task_id=task_id)
    )
    try:
        result = AgentComm(active_root, config=cfg).send(
            recipient=agent_id,
            message=full_message,
            kind="TASK_ASSIGN",
            sender=sender,
            task_id=task_id,
            tmux_target=target,
        )
        return result.ok
    except Exception as exc:
        _record_send_failure(active_root, agent_id, task_id, sender, exc)
        return False


def _agent_tmux_target(root: Path, agent_id: str) -> Optional[str]:
    registry = load_agent_registry(root)
    agent_cfg = registry.get("agent", {}).get(agent_id, {})
    target = agent_cfg.get("tmux_target")
    return str(target) if target else None


def _record_send_failure(
    root: Path,
    agent_id: str,
    task_id: str,
    sender: str,
    error: Exception,
) -> None:
    import sys
    import traceback
    from datetime import datetime, timezone

    print(f"send_task({agent_id}, {task_id}) failed: {error}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    try:
        events_path = root / "agent_context" / "task_events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "comm.failed",
                "kind": "TASK_ASSIGN",
                "sender": sender,
                "recipient": agent_id,
                "task_id": task_id,
                "error": f"send_task exception: {error}",
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, ensure_ascii=False) + "\n")
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)


def watch_task(
    task_id: str,
    root: Optional[Path] = None,
    timeout: int = 300,
    poll_interval: float = 2.0,
    relay: bool = True,
) -> Dict[str, Any]:
    """Wait for a task done-signal and optionally relay it to Claude."""
    if root is None:
        root = Path(__file__).resolve().parents[3]
    done_file = root / "agent_context" / "done" / f"{task_id}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if done_file.exists():
            try:
                result = json.loads(done_file.read_text(encoding="utf-8"))
            except Exception:
                result = {"task_id": task_id, "done_file": str(done_file)}
            if relay:
                relay_result_to_claude(task_id, result, root)
            return result
        time.sleep(poll_interval)
    return {"task_id": task_id, "timed_out": True}


def relay_result_to_claude(task_id: str, result: Dict[str, Any], root: Path) -> None:
    """Relay a done-signal summary through AgentComm."""
    from memory_os.toolkit.agent_comm import AgentComm

    sender = result.get("sender", "agent")
    message = result.get("message", "(no message)")
    summary = f"\n[SWARM RESULT task={task_id}] from {sender}:\n{message}\n"
    try:
        AgentComm(root).send_direct(
            recipient="claude",
            message=summary,
            sender="swarm",
            task_id=task_id,
        )
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)
