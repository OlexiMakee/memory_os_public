import json
from pathlib import Path
from typing import List, Optional
from memory_os.core.logger import get_logger

logger = get_logger(__name__)

class PolyglotExporter:
    """Exports Memory OS nodes to native formats for Cursor, Antigravity, and Claude Code."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir

    def export_node(
        self, 
        node_id: str, 
        node_type: str, 
        summary: str, 
        evidence: List[str], 
        globs: Optional[List[str]] = None
    ):
        """Dispatches node data to all supported agent tool formats."""
        skill_types = {"rule", "fact", "config", "policy", "skill"}
        if node_type not in skill_types:
            return

        self._export_to_cursor(node_id, summary, globs)
        self._export_to_antigravity(node_id, summary, evidence)
        self._export_to_claude(node_id, node_type, summary, evidence)

    def _export_to_cursor(self, node_id: str, summary: str, globs: Optional[List[str]]):
        """Export to .cursor/rules/*.mdc format."""
        try:
            cursor_dir = self.root_dir / ".cursor" / "rules"
            cursor_dir.mkdir(parents=True, exist_ok=True)
            cursor_path = cursor_dir / f"{node_id}.mdc"
            
            always_apply = "true" if not globs else "false"
            globs_str = ", ".join(globs) if globs else ""
            
            lines = [
                "---",
                f"description: {summary}"
            ]
            if globs_str:
                lines.append(f"globs: {globs_str}")
            lines.append(f"alwaysApply: {always_apply}")
            lines.append("---")
            lines.append("")
            lines.append(f"# {node_id}")
            lines.append("")
            lines.append(summary)
            
            with open(cursor_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as exc:
            logger.error(f"Failed to export Cursor rule for {node_id}: {exc}")

    def _export_to_antigravity(self, node_id: str, summary: str, evidence: List[str]):
        """Export to agent_context/knowledge/ format for Antigravity."""
        try:
            ki_dir = self.root_dir / "agent_context" / "knowledge" / node_id
            ki_dir.mkdir(parents=True, exist_ok=True)
            artifacts_dir = ki_dir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            
            meta_path = ki_dir / "metadata.json"
            artifact_path = artifacts_dir / f"{node_id}_details.md"
            
            # Write artifact
            artifact_lines = [
                f"# Knowledge Item: {node_id}",
                "",
                f"## Summary",
                summary,
                "",
                f"## References & Evidence"
            ]
            for ev in evidence:
                artifact_lines.append(f"- {ev}")
                
            with open(artifact_path, "w", encoding="utf-8") as f:
                f.write("\n".join(artifact_lines))
                
            # Write metadata.json
            import datetime
            metadata = {
                "summary": summary,
                "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
                "references": evidence
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
                
        except Exception as exc:
            logger.error(f"Failed to export Antigravity KI for {node_id}: {exc}")

    def _export_to_claude(self, node_id: str, node_type: str, summary: str, evidence: List[str]):
        """Export to .claude/skills/ format."""
        try:
            claude_dir = self.root_dir / ".claude" / "skills"
            claude_dir.mkdir(parents=True, exist_ok=True)
            claude_path = claude_dir / f"{node_id}.md"
            
            lines = [
                "---",
                f"name: {node_id}",
                f"description: {summary}",
                "---",
                f"# {node_id}",
                "",
                f"**Type:** {node_type}",
                "",
                "## Definition",
                summary,
                "",
                "## Evidence & Affected Files"
            ]
            for ev in evidence:
                lines.append(f"- {ev}")
                
            with open(claude_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as exc:
            logger.error(f"Failed to export Claude skill for {node_id}: {exc}")
