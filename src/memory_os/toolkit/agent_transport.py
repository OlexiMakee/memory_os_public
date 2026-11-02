"""Transport backends for delivering agent messages.

Memory OS communication is file-backed first. Interactive wake-up is a
pluggable transport concern: tmux is useful on Unix, but not required for
Windows or headless virtual-console agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


@dataclass
class TransportResult:
    ok: bool
    backend: str
    target: Optional[str] = None
    error: Optional[str] = None


class AgentTransport(Protocol):
    name: str

    def send_text(
        self,
        target: str,
        message: str,
        *,
        submit: bool = True,
        unlock_buffers: bool = True,
    ) -> TransportResult:
        ...

    def capture_text(self, target: str, *, lines: int = 80, full_history: bool = False) -> Optional[str]:
        ...


class FileInboxTransport:
    """No-op wake transport for file/inbox driven agents."""

    name = "file"
    interactive = False

    def __init__(self, root: Path):
        self.root = root

    def send_text(
        self,
        target: str,
        message: str,
        *,
        submit: bool = True,
        unlock_buffers: bool = True,
    ) -> TransportResult:
        return TransportResult(ok=True, backend=self.name, target=target)

    def capture_text(self, target: str, *, lines: int = 80, full_history: bool = False) -> Optional[str]:
        return None


class MultiplexerAgentTransport:
    """Interactive wake-up via the active terminal multiplexer (tmux or zellij).

    Delegates to MultiplexerManager, which resolves the actual runtime from
    the workspace state file; `name` reports that runtime honestly instead of
    hardcoding "tmux"."""

    interactive = True

    def __init__(self, root: Path):
        self.root = root

    @property
    def name(self) -> str:
        try:
            from memory_os.toolkit.multiplexer_manager import MultiplexerManager

            return MultiplexerManager(self.root).runtime
        except Exception:
            return "tmux"

    def send_text(
        self,
        target: str,
        message: str,
        *,
        submit: bool = True,
        unlock_buffers: bool = True,
    ) -> TransportResult:
        try:
            from memory_os.toolkit.multiplexer_manager import MultiplexerManager

            mgr = MultiplexerManager(self.root)
            mgr.send_keys(
                target=target,
                message=message,
                submit=submit,
                unlock_buffers=unlock_buffers,
            )
            return TransportResult(ok=True, backend=self.name, target=target)
        except Exception as exc:
            return TransportResult(ok=False, backend=self.name, target=target, error=str(exc))

    def capture_text(self, target: str, *, lines: int = 80, full_history: bool = False) -> Optional[str]:
        try:
            from memory_os.toolkit.multiplexer_manager import MultiplexerManager

            return MultiplexerManager(self.root).capture_pane(target, lines=lines, full_history=full_history)
        except Exception:
            return None
