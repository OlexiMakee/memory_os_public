"""Agent prompt principle synchronization for workspace launches."""

from __future__ import annotations

from pathlib import Path

from memory_os.toolkit.agent_registry import load_agent_registry


PRINCIPLE_SENTINEL = 'Update "src/memory_os/docs/encyclopedia/cli_tools.md" immediately when writing new tools'

PRINCIPLES_PREAMBLE = """\
[SYSTEM: NO praise/flattery. Criticize directly. Scan codebase/web & compare alternative paths before editing. Search memory first: "memory_os search <topic>". Work 100% autonomously: NEVER ask user for input/choices/confirmation unless explicitly requested to interview/grill user for planning. Record evidence for audit: "memory_os evidence add-command --task-id <id> -- <cmd>". Write completed decisions to memory: "memory_os memory write --type fact --summary '<decisions>'". For all other capabilities, ALWAYS use the official memory_os tools documented in "src/memory_os/docs/encyclopedia/cli_tools.md". Update "src/memory_os/docs/encyclopedia/cli_tools.md" immediately when writing new tools or modifying existing ones. Run tests. Mandatory done report: "memory_os comm send --kind STATUS_REPORT --sender <agent_id> --task-id <id> <task_initiator> '<files | pytest | risks>'".]

"""


class PromptPrincipleSync:
    def __init__(self, root: Path):
        self.root = root

    def sync(self) -> list[Path]:
        registry = load_agent_registry(self.root, fallback_to_main=True).get("agent", {})
        updated: list[Path] = []
        for config in registry.values():
            if config.get("kind") != "cli_agent":
                continue
            prompt_file_rel = config.get("system_prompt_file")
            if not prompt_file_rel:
                continue
            prompt_file = self.root / prompt_file_rel
            if not prompt_file.exists():
                continue
            content = prompt_file.read_text(encoding="utf-8")
            if PRINCIPLE_SENTINEL in content:
                continue
            prompt_file.write_text(
                PRINCIPLES_PREAMBLE + self._without_old_preamble(content),
                encoding="utf-8",
            )
            updated.append(prompt_file)
        return updated

    @staticmethod
    def _without_old_preamble(content: str) -> str:
        clean_lines: list[str] = []
        skip = False
        for line in content.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith("[SYSTEM:")
                or stripped.startswith("# Memory OS Operating Principles")
                or stripped.startswith("# Memory OS — Agent Operating Principles")
            ):
                skip = True
                continue
            if skip and not stripped:
                continue
            skip = False
            clean_lines.append(line)
        return "\n".join(clean_lines)
