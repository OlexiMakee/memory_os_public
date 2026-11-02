"""Handoff Builder — generates a markdown context pack for agent-to-agent handoffs.

Usage:
    builder = HandoffBuilder(root)
    path = builder.build("task_abc123")
    memory_os handoff build --task-id task_abc123
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class HandoffBuilder:
    def __init__(self, root: Path):
        self.root = root

    def _load_nodes(self, limit: int = 10) -> List[Dict[str, Any]]:
        nodes_path = self.root / "memory" / "nodes.jsonl"
        if not nodes_path.exists():
            return []
        nodes = []
        for line in nodes_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                n = json.loads(line)
            except json.JSONDecodeError:
                continue
            if n.get("status") != "archived":
                nodes.append(n)
        # Sort by created_at descending, take most recent
        nodes.sort(key=lambda n: n.get("created_at", ""), reverse=True)
        return nodes[:limit]

    def _list_evidence(self, task_id: str) -> List[str]:
        evidence_dir = self.root / "agent_context" / "evidence" / task_id
        if not evidence_dir.exists():
            return []
        return sorted(f.name for f in evidence_dir.iterdir() if f.is_file())

    def build(
        self,
        task_id: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        from memory_os.toolkit.task_kernel import TaskKernel

        kernel = TaskKernel(self.root)
        task = kernel.get(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        events = kernel.events(task_id=task_id)
        nodes = self._load_nodes()
        evidence_files = self._list_evidence(task_id)

        if output_path is None:
            output_path = self.root / "agent_context" / "context_packs" / f"handoff_{task_id}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines: List[str] = []

        lines.append(f"# Handoff — {task_id}")
        lines.append("")

        # Task summary
        lines.append("## Task")
        lines.append(f"- **Title**: {task.get('title', '?')}")
        if task.get("goal"):
            lines.append(f"- **Goal**: {task['goal']}")
        lines.append(f"- **Status**: {task.get('status', '?')}")
        lines.append(f"- **Risk**: {task.get('risk', '?')}")
        if task.get("agent"):
            lines.append(f"- **Agent**: {task['agent']}")
        if task.get("capabilities"):
            lines.append(f"- **Capabilities**: {', '.join(task['capabilities'])}")
        if task.get("blocked_reason"):
            lines.append(f"- **Blocked reason**: {task['blocked_reason']}")
        if task.get("done_criteria"):
            lines.append(f"- **Done criteria**: {task['done_criteria']}")
        if task.get("handoff_summary"):
            lines.append(f"- **Handoff summary**: {task['handoff_summary']}")
        lines.append("")

        # Timeline
        if events:
            lines.append("## Timeline")
            lines.append("| Time | Event | Agent | Reason |")
            lines.append("|------|-------|-------|--------|")
            for e in events:
                ts = e.get("ts", "?")
                event = e.get("event", "?")
                agent = e.get("agent", "—")
                reason = e.get("reason", "—")
                lines.append(f"| {ts} | {event} | {agent} | {reason} |")
            lines.append("")

        # Lease
        if task.get("lease_owner"):
            lines.append("## Lease")
            lines.append(f"- **Owner**: {task['lease_owner']}")
            lines.append(f"- **Expires**: {task.get('lease_expires', '?')}")
            lines.append("")

        # Memory context
        if nodes:
            lines.append("## Recent Memory Context (last 10 nodes)")
            lines.append("| ID | Type | Summary |")
            lines.append("|----|------|---------|")
            for n in nodes:
                nid = n.get("id", "?")[:12]
                ntype = n.get("type", "?")
                summary = (n.get("summary") or "")[:80].replace("|", "\\|")
                lines.append(f"| {nid} | {ntype} | {summary} |")
            lines.append("")

        # Evidence
        lines.append("## Evidence Files")
        if evidence_files:
            for f in evidence_files:
                lines.append(f"- `{f}`")
        else:
            lines.append("No evidence files found.")
        lines.append("")

        # Next steps
        lines.append("## Next Steps for Incoming Agent")
        lines.append("- Review task goal and current status above")
        if evidence_files:
            lines.append(f"- Check evidence files in `agent_context/evidence/{task_id}/`")
        if task.get("status") == "blocked":
            lines.append(f"- Task is BLOCKED: address `{task.get('blocked_reason', '?')}` before proceeding")
        elif task.get("status") == "review":
            lines.append("- Task is in REVIEW: verify output and mark done or return to running")
        elif task.get("status") == "pending":
            lines.append("- Claim the task: `memory_os task claim {task_id} --agent <your-id>`")
        lines.append(f"- Update status: `memory_os task status {task_id}`")
        lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path
