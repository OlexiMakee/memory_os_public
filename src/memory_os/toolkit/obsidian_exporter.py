import json
import shutil
from pathlib import Path
from typing import Dict, List, Any
from memory_os.core.logger import get_logger
from memory_os.core.safe_id import validate_safe_node_id

logger = get_logger(__name__)

def export_obsidian_vault(root_dir: Path, nodes_path: Path, edges_path: Path):
    """Exports Memory OS graph to an Obsidian Vault format."""
    vault_dir = root_dir / "data" / "obsidian_vault"
    
    if not nodes_path.exists() or not edges_path.exists():
        logger.error("Memory OS graph files not found.")
        return False
        
    try:
        if vault_dir.exists():
            shutil.rmtree(vault_dir)
        vault_dir.mkdir(parents=True, exist_ok=True)
        
        with open(nodes_path, "r", encoding="utf-8") as f:
            nodes = [json.loads(line) for line in f if line.strip()]
            
        with open(edges_path, "r", encoding="utf-8") as f:
            edges = [json.loads(line) for line in f if line.strip()]
            
        # Group edges by source
        edges_by_source: Dict[str, List[Dict[str, Any]]] = {}
        for edge in edges:
            src = edge.get("source")
            if src not in edges_by_source:
                edges_by_source[src] = []
            edges_by_source[src].append(edge)
            
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue
            try:
                validate_safe_node_id(node_id)
            except (ValueError, TypeError) as exc:
                logger.error(f"Skipping node with unsafe id {node_id!r}: {exc}")
                continue

            node_path = vault_dir / f"{node_id}.md"
            
            # YAML Frontmatter
            lines = [
                "---",
                f"id: {node_id}",
                f"type: {node.get('type', 'unknown')}",
                f"trust: {node.get('trust', 'unknown')}",
                f"status: {node.get('status', 'unknown')}"
            ]
            
            tags = node.get("tags", [])
            if tags:
                lines.append("tags:")
                for tag in tags:
                    lines.append(f"  - {tag}")
                    
            lines.append("---")
            lines.append("")
            
            # Content
            lines.append(f"# {node_id}")
            lines.append("")
            lines.append(node.get("summary", ""))
            lines.append("")
            
            # Evidence
            evidence = node.get("evidence", [])
            if evidence:
                lines.append("## Evidence")
                for ev in evidence:
                    lines.append(f"- {ev}")
                lines.append("")
                
            # Links (Edges)
            out_edges = edges_by_source.get(node_id, [])
            if out_edges:
                lines.append("## Connections")
                for edge in out_edges:
                    target = edge.get("target")
                    rel_type = edge.get("type", "relates_to")
                    lines.append(f"- **{rel_type}** [[{target}]]")
                lines.append("")
                
            # Related nodes (Implicit)
            related = node.get("related_nodes", [])
            if related:
                lines.append("## Related Nodes")
                for rel in related:
                    lines.append(f"- [[{rel}]]")
                lines.append("")
                
            with open(node_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                
        logger.info(f"Successfully exported {len(nodes)} nodes to Obsidian Vault at {vault_dir}")
        return True
        
    except Exception as exc:
        logger.error(f"Failed to export Obsidian Vault: {exc}")
        return False
