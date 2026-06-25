from memory_os.core.logger import get_logger
logger = get_logger(__name__)
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Any, Tuple, Optional

from memory_os.core.interfaces import IMemoryOSConfig, IMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import validate_safe_node_id
from memory_os.core.storage import FileSystemMemoryStorage

class LifecycleManager:
    """Manages the lifecycle operations of Memory OS files (propose, transition, manifest, prune)."""

    def __init__(
        self,
        config: Optional[IMemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None
    ):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(self.storage, self.config)

    def _sha256_file(self, path: Path) -> str:
        return self.storage.get_sha256(path)

    def _load_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(path)

    def _write_jsonl(self, path: Path, items: List[Dict[str, Any]]) -> None:
        self.storage.save_jsonl(path, items)

    def _append_jsonl(self, path: Path, item: Dict[str, Any]) -> None:
        self.storage.append_jsonl(path, item)

    def _validate_evidence(self, evidence_list: List[str]) -> bool:
        for item in evidence_list:
            if not item.startswith("http"):
                if not self.storage.exists(self.config.root_dir / item):
                    return False
        return True

    def propose(self, node_id: str, node_type: str, summary: str, evidence: str,
                related_nodes: Optional[str] = None, validator: Optional[str] = None,
                tags: Optional[str] = None) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        events_file = self.config.memory_dir / "events.jsonl"

        nodes = self._load_jsonl(nodes_file)
        for n in nodes:
            if n["id"] == node_id:
                logger.info(f"ERROR: Node '{node_id}' already exists.")
                return 1

        evidence_list = [e.strip() for e in evidence.split(",") if e.strip()]
        related = [r.strip() for r in related_nodes.split(",") if r.strip()] if related_nodes else []
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        new_node = {
            "id": node_id,
            "type": node_type,
            "summary": summary,
            "evidence": evidence_list,
            "status": "draft",
            "freshness": datetime.now().isoformat(timespec="seconds"),
            "trust": "unverified",
            "related_nodes": related,
            "tags": tag_list,
        }

        self._append_jsonl(nodes_file, new_node)
        logger.info(f"INFO: Proposed node '{node_id}' added as draft.")

        new_event = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": "memory.node.proposed",
            "node_id": node_id,
            "claim": f"Propose rule/fact: {summary}",
            "evidence": evidence_list,
            "validator": validator or "cli_proposer",
            "status": "pending"
        }
        self._append_jsonl(events_file, new_event)
        return 0

    def transition(self, validator: Optional[str] = None) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        edges_file = self.config.memory_dir / "edges.jsonl"
        events_file = self.config.memory_dir / "events.jsonl"

        nodes = self._load_jsonl(nodes_file)
        edges = self._load_jsonl(edges_file)
        events = self._load_jsonl(events_file)

        # Snapshot of nodes that were already verified before this call.
        # Used by the override-chain logic below so that a node's source_verified
        # status is evaluated against a stable set, not the mutating updated_nodes.
        pre_verified_ids: Set[str] = {n["id"] for n in nodes if n.get("status") == "verified"}

        updated_nodes = []
        verified_ids: Set[str] = set()  # newly promoted in this call
        new_events = []

        for node in nodes:
            if node["status"] in ["draft", "observed"]:
                if not node.get("id") or not node.get("summary") or node.get("type") not in ["rule", "fact", "variable", "connector", "config", "policy", "module_cluster"]:
                    logger.info(f"INFO: Rejecting transition for node '{node['id']}': invalid schema.")
                    node["status"] = "stale"
                    for ev in events:
                        if ev.get("node_id") == node["id"] and ev.get("event") == "memory.node.proposed" and ev.get("status") == "pending":
                            ev["status"] = "rejected"
                            ev["claim"] += " [Rejected: schema violation]"
                elif not self._validate_evidence(node["evidence"]):
                    logger.info(f"INFO: Rejecting transition for node '{node['id']}': missing evidence files.")
                    node["status"] = "stale"
                    for ev in events:
                        if ev.get("node_id") == node["id"] and ev.get("event") == "memory.node.proposed" and ev.get("status") == "pending":
                            ev["status"] = "rejected"
                            ev["claim"] += " [Rejected: missing evidence]"
                else:
                    logger.info(f"INFO: Transitioning node '{node['id']}' to verified.")
                    node["status"] = "verified"
                    node["trust"] = "verified"
                    node["freshness"] = datetime.now().isoformat(timespec="seconds")
                    verified_ids.add(node["id"])
                    for ev in events:
                        if ev.get("node_id") == node["id"] and ev.get("event") == "memory.node.proposed" and ev.get("status") == "pending":
                            ev["status"] = "accepted"

                    verification_event = {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "event": "memory.node.verified",
                        "node_id": node["id"],
                        "claim": f"Verified node: {node['summary']}",
                        "evidence": node["evidence"],
                        "validator": validator or "lifecycle_manager",
                        "status": "accepted"
                    }
                    new_events.append(verification_event)

                    if node.get("type") == "rule":
                        self._emit_skill_file(node)

            updated_nodes.append(node)

        # Stable verified set: pre-existing + newly promoted this call.
        # Evaluated as a snapshot so transitive chains (A→B→C) resolve correctly
        # even when B is superseded mid-loop before its own outgoing edges are checked.
        all_verified_ids: Set[str] = pre_verified_ids | verified_ids

        # Handle overrides/refutations
        for edge in edges:
            if edge["type"] in ["overrides", "refutes"]:
                source_id = edge["source"]
                target_id = edge["target"]

                source_verified = source_id in all_verified_ids

                if source_verified:
                    for n in updated_nodes:
                        if n["id"] == target_id and n["status"] not in ["stale", "superseded"]:
                            new_status = "superseded" if edge["type"] == "overrides" else "stale"
                            logger.info(f"INFO: Node '{target_id}' is deprecating to '{new_status}' due to edge '{edge['type']}' from '{source_id}'.")
                            n["status"] = new_status
                            n["freshness"] = datetime.now().isoformat(timespec="seconds")

                            dep_event = {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "event": "memory.node.deprecated",
                                "node_id": target_id,
                                "claim": f"Deprecated to {new_status} via edge {edge['type']} from {source_id}",
                                "evidence": n["evidence"],
                                "validator": validator or "lifecycle_manager",
                                "status": "accepted"
                            }
                            new_events.append(dep_event)

        self._write_jsonl(nodes_file, updated_nodes)
        self._write_jsonl(events_file, events + new_events)
        logger.info("INFO: Transition processing completed.")
        return 0

    def _emit_skill_file(self, node: Dict[str, Any]) -> None:
        try:
            validate_safe_node_id(node["id"])
        except ValueError as exc:
            # Defense in depth: a node this unsafe should already be rejected
            # by EvolutionGate/MemoryValidator, but skip rather than write
            # outside .claude/skills/ if one slips through.
            logger.error(f"Refusing to emit skill file for unsafe node id {node.get('id')!r}: {exc}")
            return
        skills_dir = self.config.root_dir / ".claude" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skills_dir / f"{node['id']}.md"
        summary = node.get("summary", "")
        if not isinstance(summary, str):
            summary = str(summary)
        lines = [f"# {node['id']}", "", summary, ""]
        evidence = node.get("evidence", [])
        if evidence:
            lines += ["**Evidence:**"] + [f"- {ev}" for ev in evidence] + [""]
        tags = node.get("tags", [])
        if tags:
            lines.append(f"**Tags:** {', '.join(tags)}")
        skill_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"INFO: Emitted skill file: {skill_path.name}")

    def manifest(self) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        edges_file = self.config.memory_dir / "edges.jsonl"
        events_file = self.config.memory_dir / "events.jsonl"

        nodes = self._load_jsonl(nodes_file)
        edges = self._load_jsonl(edges_file)
        events = self._load_jsonl(events_file)

        node_statuses = {}
        node_types = {}
        for n in nodes:
            node_statuses[n["status"]] = node_statuses.get(n["status"], 0) + 1
            node_types[n["type"]] = node_types.get(n["type"], 0) + 1

        edge_types = {}
        for e in edges:
            edge_types[e["type"]] = edge_types.get(e["type"], 0) + 1

        event_statuses = {}
        for ev in events:
            event_statuses[ev["status"]] = event_statuses.get(ev["status"], 0) + 1

        manifest_data = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "counts": {
                "nodes": len(nodes),
                "node_statuses": node_statuses,
                "node_types": node_types,
                "edges": len(edges),
                "edge_types": edge_types,
                "events": len(events),
                "event_statuses": event_statuses
            },
            "checksums": {
                "nodes.jsonl": self._sha256_file(nodes_file),
                "edges.jsonl": self._sha256_file(edges_file),
                "events.jsonl": self._sha256_file(events_file)
            }
        }

        manifest_path = self.config.memory_dir / "manifest.json"
        self.storage.save_json(manifest_path, manifest_data)

        try:
            rel_manifest = manifest_path.relative_to(self.config.root_dir)
        except ValueError:
            rel_manifest = manifest_path
        logger.info(f"INFO: Wrote manifest to {rel_manifest}")
        return 0

    def prune(self) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        edges_file = self.config.memory_dir / "edges.jsonl"

        nodes = self._load_jsonl(nodes_file)
        edges = self._load_jsonl(edges_file)

        pruned_nodes = []
        active_node_ids = set()
        pruned_count = 0
        
        archived_nodes_list = []
        archived_edges_list = []

        for n in nodes:
            if n["status"] in ["stale", "superseded"]:
                logger.info(f"INFO: Pruning stale/superseded node '{n['id']}'.")
                archived_nodes_list.append(n)
                pruned_count += 1
            else:
                pruned_nodes.append(n)
                active_node_ids.add(n["id"])

        pruned_edges = []
        pruned_edges_count = 0
        for e in edges:
            if e["source"] == e["target"]:
                logger.info(f"INFO: Pruning self-referential edge: {e['source']} -> {e['target']} ({e['type']})")
                pruned_edges_count += 1
            elif e["source"] in active_node_ids and e["target"] in active_node_ids:
                pruned_edges.append(e)
            else:
                logger.info(f"INFO: Pruning dangling edge: {e['source']} -> {e['target']} ({e['type']})")
                archived_edges_list.append(e)
                pruned_edges_count += 1

        self._write_jsonl(nodes_file, pruned_nodes)
        self._write_jsonl(edges_file, pruned_edges)
        
        if archived_nodes_list:
            archived_nodes_file = self.config.memory_dir / "archived_nodes.jsonl"
            for an in archived_nodes_list:
                self._append_jsonl(archived_nodes_file, an)
                
        if archived_edges_list:
            archived_edges_file = self.config.memory_dir / "archived_edges.jsonl"
            for ae in archived_edges_list:
                self._append_jsonl(archived_edges_file, ae)

        logger.info(f"INFO: Pruning finished. Archived {pruned_count} nodes and {len(archived_edges_list)} edges. Removed {pruned_edges_count - len(archived_edges_list)} invalid edges.")
        return 0
