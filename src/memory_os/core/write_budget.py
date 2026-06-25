"""Bounded write budget for local agent artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import confine_to_root


DEFAULT_WRITE_BUDGET: Dict[str, Any] = {
    "enabled": True,
    "max_agent_context_mb": 64,
    "max_agent_context_files": 2000,
    "max_single_write_mb": 4,
}


@dataclass(frozen=True)
class WriteBudgetStatus:
    enabled: bool
    agent_context_mb: float
    max_agent_context_mb: float
    agent_context_files: int
    max_agent_context_files: int
    max_single_write_mb: float
    over_size_cap: bool
    over_file_cap: bool

    @property
    def ok(self) -> bool:
        return not self.over_size_cap and not self.over_file_cap

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "agent_context_mb": self.agent_context_mb,
            "max_agent_context_mb": self.max_agent_context_mb,
            "agent_context_files": self.agent_context_files,
            "max_agent_context_files": self.max_agent_context_files,
            "max_single_write_mb": self.max_single_write_mb,
            "over_size_cap": self.over_size_cap,
            "over_file_cap": self.over_file_cap,
            "ok": self.ok,
        }


class WriteBudgetExceeded(RuntimeError):
    pass


class ArtifactWriteBudget:
    """Checks bounded local writes under agent_context before saving artifacts."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.settings: Dict[str, Any] = {
            **DEFAULT_WRITE_BUDGET,
            **config.data.get("write_budget", {}),
        }
        self.agent_context_dir = confine_to_root("agent_context", config.root_dir)

    def _agent_context_usage(self) -> Dict[str, Any]:
        total_bytes = 0
        file_count = 0
        if self.agent_context_dir.is_dir():
            for path in self.agent_context_dir.glob("**/*"):
                if not path.is_file():
                    continue
                try:
                    total_bytes += path.stat().st_size
                    file_count += 1
                except OSError:
                    continue
        return {
            "bytes": total_bytes,
            "mb": round(total_bytes / (1024 * 1024), 3),
            "files": file_count,
        }

    def status(self) -> WriteBudgetStatus:
        usage = self._agent_context_usage()
        max_mb = float(self.settings["max_agent_context_mb"])
        max_files = int(self.settings["max_agent_context_files"])
        return WriteBudgetStatus(
            enabled=bool(self.settings["enabled"]),
            agent_context_mb=usage["mb"],
            max_agent_context_mb=max_mb,
            agent_context_files=usage["files"],
            max_agent_context_files=max_files,
            max_single_write_mb=float(self.settings["max_single_write_mb"]),
            over_size_cap=usage["mb"] > max_mb,
            over_file_cap=usage["files"] > max_files,
        )

    def assert_can_write(self, target_path: Path, bytes_to_write: int) -> None:
        if not bool(self.settings["enabled"]):
            return

        target = confine_to_root(str(target_path), self.config.root_dir)
        try:
            target.relative_to(self.agent_context_dir)
        except ValueError:
            return

        max_single_bytes = int(float(self.settings["max_single_write_mb"]) * 1024 * 1024)
        if bytes_to_write > max_single_bytes:
            raise WriteBudgetExceeded(
                f"single artifact write is {bytes_to_write} bytes "
                f"(cap {self.settings['max_single_write_mb']} MB)"
            )

        usage = self._agent_context_usage()
        existing_size = target.stat().st_size if target.exists() else 0
        projected_bytes = usage["bytes"] - existing_size + bytes_to_write
        projected_mb = projected_bytes / (1024 * 1024)
        max_mb = float(self.settings["max_agent_context_mb"])
        if projected_mb > max_mb:
            raise WriteBudgetExceeded(
                f"agent_context would become {projected_mb:.3f} MB "
                f"(cap {max_mb} MB)"
            )

        projected_files = usage["files"] if target.exists() else usage["files"] + 1
        max_files = int(self.settings["max_agent_context_files"])
        if projected_files > max_files:
            raise WriteBudgetExceeded(
                f"agent_context would contain {projected_files} files "
                f"(cap {max_files})"
            )

    def write_text(self, target_path: Path, text: str, encoding: str = "utf-8") -> None:
        encoded = text.encode(encoding)
        self.assert_can_write(target_path, len(encoded))
        target_path.write_text(text, encoding=encoding)
