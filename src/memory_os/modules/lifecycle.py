from memory_os.core.logger import get_logger
logger = get_logger(__name__)
from pathlib import Path
from typing import List, Dict, Set, Any, Optional

from memory_os.core.interfaces import IMemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.config import MemoryOSConfig
from memory_os.core.node_stats import NodeStatsStore
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.timecode import now_local_iso

PROMOTABLE_NODE_TYPES = frozenset({"rule", "fact", "variable", "connector", "config", "policy", "module_cluster"})

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

    def _apply_graph_patch(self, patch: Any, events: Optional[List[Dict[str, Any]]] = None) -> bool:
        from memory_os.core.patch import RelationPatchStore
        patch_store = RelationPatchStore(self.repository)
        patch_id = patch_store.propose(patch)
        return patch_store.apply(patch_id, events=events)

    def _upsert_node_via_patch(self, node: Dict[str, Any], events: Optional[List[Dict[str, Any]]] = None) -> bool:
        patch = self.repository._make_patch(
            operation="upsert_node",
            target=node.get("id", ""),
            patch_type=node.get("type", "fact"),
            confidence=float(node.get("confidence", 1.0) or 1.0),
            evidence=node.get("evidence", []),
            payload={"node": dict(node)},
            reason=f"lifecycle upsert node {node.get('id', '')}",
        )
        return self._apply_graph_patch(patch, events=events)

    def _replace_nodes_via_patch(
        self,
        nodes: List[Dict[str, Any]],
        events: Optional[List[Dict[str, Any]]] = None,
        reason: str = "lifecycle replace nodes",
    ) -> bool:
        patch = self.repository._make_patch(
            operation="replace_nodes",
            target="memory/nodes.jsonl",
            payload={"nodes": [dict(node) for node in nodes]},
            reason=reason,
        )
        return self._apply_graph_patch(patch, events=events)

    def _sha256_file(self, path: Path) -> str:
        return self.storage.get_sha256(path)

    def _load_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(path)

    def _validate_evidence(self, evidence_list: List[str]) -> bool:
        for item in evidence_list:
            if not item.startswith("http"):
                if not self.storage.exists(self.config.root_dir / item):
                    return False
        return True

    def _confidence_threshold(self, min_confidence: Optional[float] = None) -> float:
        if min_confidence is not None:
            return float(min_confidence)
        return float(self.config.confidence_threshold)

    def propose(self, node_id: str, node_type: str, summary: str, evidence: str,
                related_nodes: Optional[str] = None, validator: Optional[str] = None,
                tags: Optional[str] = None, confidence: float = 1.0) -> int:
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
            "freshness": now_local_iso(self.config),
            "trust": "unverified",
            "related_nodes": related,
            "tags": tag_list,
            "confidence": float(confidence),
        }

        if not self._upsert_node_via_patch(new_node):
            logger.info(f"ERROR: Failed to propose node '{node_id}'.")
            return 1
        logger.info(f"INFO: Proposed node '{node_id}' added as draft.")

        new_event = {
            "timestamp": now_local_iso(self.config),
            "event": "memory.node.proposed",
            "node_id": node_id,
            "claim": f"Propose rule/fact: {summary}",
            "evidence": evidence_list,
            "validator": validator or "cli_proposer",
            "status": "pending"
        }
        self.repository.emit_event(new_event)
        return 0

    def propose_candidate(
        self,
        node_id: str,
        node_type: str,
        summary: str,
        evidence: str | List[str],
        confidence: float,
        related_nodes: Optional[str | List[str]] = None,
        validator: Optional[str] = None,
        tags: Optional[str | List[str]] = None,
    ) -> int:
        evidence_text = ",".join(evidence) if isinstance(evidence, list) else evidence
        related_text = ",".join(related_nodes) if isinstance(related_nodes, list) else related_nodes
        tag_text = ",".join(tags) if isinstance(tags, list) else tags
        return self.propose(
            node_id=node_id,
            node_type=node_type,
            summary=summary,
            evidence=evidence_text,
            related_nodes=related_text,
            validator=validator or "candidate_proposer",
            tags=tag_text,
            confidence=confidence,
        )

    def _candidate_rejection(self, node: Dict[str, Any], min_confidence: float) -> Optional[str]:
        if not node.get("id") or not node.get("summary") or node.get("type") not in PROMOTABLE_NODE_TYPES:
            return "schema violation"
        evidence = node.get("evidence") or []
        if not isinstance(evidence, list) or not self._validate_evidence(evidence):
            return "missing evidence"
        confidence = float(node.get("confidence", 1.0) or 1.0)
        if confidence < min_confidence:
            return f"confidence {confidence:.2f} below threshold {min_confidence:.2f}"
        return None

    def _close_pending_proposal(self, events: List[Dict[str, Any]], node_id: str, status: str, suffix: str = "") -> None:
        for ev in events:
            if ev.get("node_id") == node_id and ev.get("event") == "memory.node.proposed" and ev.get("status") == "pending":
                ev["status"] = status
                if suffix:
                    ev["claim"] = f"{ev.get('claim', '')} {suffix}".strip()

    def promote(self, node_id: str, validator: Optional[str] = None) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        events_file = self.config.memory_dir / "events.jsonl"
        nodes = self._load_jsonl(nodes_file)
        events = self._load_jsonl(events_file)
        now_str = now_local_iso(self.config)

        for node in nodes:
            if node.get("id") != node_id:
                continue
            rejection = self._candidate_rejection(node, min_confidence=0.0)
            if rejection:
                logger.info(f"INFO: Refusing explicit promote for node '{node_id}': {rejection}.")
                return 1
            node["status"] = "verified"
            node["trust"] = "verified"
            node["freshness"] = now_str
            if not node.get("valid_from"):
                node["valid_from"] = now_str
            self._close_pending_proposal(events, node_id, "accepted", "[Explicitly promoted]")
            new_events = [{
                "timestamp": now_str,
                "event": "memory.node.verified",
                "node_id": node_id,
                "claim": f"Explicitly promoted node: {node.get('summary', '')}",
                "evidence": node.get("evidence", []),
                "validator": validator or "lifecycle_manager",
                "status": "accepted",
                "promotion_mode": "explicit",
            }]
            if not self._replace_nodes_via_patch(nodes, events=new_events, reason=f"explicit promote node {node_id}"):
                logger.info(f"ERROR: Failed to promote node '{node_id}'.")
                return 1
            patch_events = self.repository.get_events()[len(events):]
            self.repository.replace_events(events + patch_events)
            self._export_verified_node(node)
            return 0
        logger.info(f"ERROR: Node '{node_id}' not found.")
        return 1

    def reject(self, node_id: str, reason: str = "", validator: Optional[str] = None) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        events_file = self.config.memory_dir / "events.jsonl"
        nodes = self._load_jsonl(nodes_file)
        events = self._load_jsonl(events_file)
        now_str = now_local_iso(self.config)

        for node in nodes:
            if node.get("id") != node_id:
                continue
            node["status"] = "stale"
            node["freshness"] = now_str
            node["valid_until"] = now_str
            suffix = f"[Rejected: {reason}]" if reason else "[Rejected]"
            self._close_pending_proposal(events, node_id, "rejected", suffix)
            new_events = [{
                "timestamp": now_str,
                "event": "memory.node.rejected",
                "node_id": node_id,
                "claim": reason or f"Rejected node: {node.get('summary', '')}",
                "evidence": node.get("evidence", []),
                "validator": validator or "lifecycle_manager",
                "status": "accepted",
            }]
            if not self._replace_nodes_via_patch(nodes, events=new_events, reason=f"reject node {node_id}"):
                logger.info(f"ERROR: Failed to reject node '{node_id}'.")
                return 1
            patch_events = self.repository.get_events()[len(events):]
            self.repository.replace_events(events + patch_events)
            return 0
        logger.info(f"ERROR: Node '{node_id}' not found.")
        return 1

    def transition(self, validator: Optional[str] = None, min_confidence: Optional[float] = None) -> int:
        nodes_file = self.config.memory_dir / "nodes.jsonl"
        edges_file = self.config.memory_dir / "edges.jsonl"
        events_file = self.config.memory_dir / "events.jsonl"
        threshold = self._confidence_threshold(min_confidence)

        nodes = self._load_jsonl(nodes_file)
        edges = self._load_jsonl(edges_file)
        events = self._load_jsonl(events_file)

        # Snapshot of nodes that were already verified before this call.
        # Used by the override-chain logic below so that a node's source_verified
        # status is evaluated against a stable set, not the mutating updated_nodes.
        pre_verified_ids: Set[str] = {n["id"] for n in nodes if n.get("status") == "verified"}

        updated_nodes = []
        verified_ids: Set[str] = set()  # newly promoted in this call
        verified_nodes: List[Dict[str, Any]] = []
        new_events = []

        for node in nodes:
            if node["status"] in ["draft", "observed"]:
                # Hard violations (schema/evidence) stale the candidate; low
                # confidence only HOLDS it in draft — it may gain evidence later
                # and be promoted by a future transition or explicit promote(),
                # mirroring the AdapterRegistry candidate pattern.
                rejection = self._candidate_rejection(node, min_confidence=0.0)
                confidence = float(node.get("confidence", 1.0) or 1.0)
                if rejection:
                    logger.info(f"INFO: Rejecting transition for node '{node['id']}': {rejection}.")
                    node["status"] = "stale"
                    now_str = now_local_iso(self.config)
                    node["freshness"] = now_str
                    node["valid_until"] = now_str
                    self._close_pending_proposal(events, node["id"], "rejected", f"[Rejected: {rejection}]")
                    new_events.append({
                        "timestamp": now_str,
                        "event": "memory.node.rejected",
                        "node_id": node["id"],
                        "claim": f"Rejected node: {rejection}",
                        "evidence": node.get("evidence", []),
                        "validator": validator or "lifecycle_manager",
                        "status": "accepted",
                    })
                elif confidence < threshold:
                    logger.info(
                        f"INFO: Holding node '{node['id']}' in draft: confidence {confidence:.2f} below threshold {threshold:.2f}."
                    )
                else:
                    logger.info(f"INFO: Transitioning node '{node['id']}' to verified.")
                    node["status"] = "verified"
                    node["trust"] = "verified"
                    now_str = now_local_iso(self.config)
                    node["freshness"] = now_str
                    if "valid_from" not in node or not node["valid_from"]:
                        node["valid_from"] = now_str
                    verified_ids.add(node["id"])
                    verified_nodes.append(node)
                    self._close_pending_proposal(events, node["id"], "accepted")

                    verification_event = {
                        "timestamp": now_str,
                        "event": "memory.node.verified",
                        "node_id": node["id"],
                        "claim": f"Verified node: {node['summary']}",
                        "evidence": node["evidence"],
                        "validator": validator or "lifecycle_manager",
                        "status": "accepted",
                        "promotion_mode": "auto",
                        "confidence_threshold": threshold,
                    }
                    new_events.append(verification_event)

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
                            now_str = now_local_iso(self.config)
                            n["freshness"] = now_str
                            n["valid_until"] = now_str

                            dep_event = {
                                "timestamp": now_str,
                                "event": "memory.node.deprecated",
                                "node_id": target_id,
                                "claim": f"Deprecated to {new_status} via edge {edge['type']} from {source_id}",
                                "evidence": n["evidence"],
                                "validator": validator or "lifecycle_manager",
                                "status": "accepted"
                            }
                            new_events.append(dep_event)

        original_event_count = len(events)
        if not self._replace_nodes_via_patch(updated_nodes, events=new_events, reason="lifecycle transition nodes"):
            logger.error("ERROR: Transition failed while applying node patch.")
            return 1
        patch_events = self.repository.get_events()[original_event_count:]
        self.repository.replace_events(events + patch_events)
        for node in verified_nodes:
            self._export_verified_node(node)
        logger.info("INFO: Transition processing completed.")
        return 0

    def _export_verified_node(self, node: Dict[str, Any]) -> None:
        from memory_os.modules.exporter import PolyglotExporter

        PolyglotExporter(self.config.root_dir).export_node(
            node_id=node["id"],
            node_type=node.get("type", "fact"),
            summary=str(node.get("summary", "")),
            evidence=list(node.get("evidence", [])),
            status=node.get("status", "draft"),
            globs=node.get("globs"),
        )

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
            "generated_at": now_local_iso(self.config),
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
            pinned = "pinned" in {str(tag) for tag in n.get("tags", [])}
            if n["status"] in ["stale", "superseded"] and not pinned:
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

        from memory_os.core.patch import RelationPatchStore

        patch_store = RelationPatchStore(self.repository)
        node_patch = self.repository._make_patch(
            operation="replace_nodes",
            target="memory/nodes.jsonl",
            payload={"nodes": pruned_nodes},
            reason="prune stale/superseded nodes",
        )
        edge_patch = self.repository._make_patch(
            operation="replace_edges",
            target="memory/edges.jsonl",
            payload={"edges": pruned_edges},
            reason="prune dangling edges",
        )
        node_patch_id = patch_store.propose(node_patch)
        edge_patch_id = patch_store.propose(edge_patch)
        if not patch_store.apply_many([node_patch_id, edge_patch_id]):
            logger.error("ERROR: Prune failed while applying graph patches.")
            return 1
        
        if archived_nodes_list:
            self.repository.archive_nodes(archived_nodes_list)
                
        if archived_edges_list:
            self.repository.archive_edges(archived_edges_list)

        logger.info(f"INFO: Pruning finished. Archived {pruned_count} nodes and {len(archived_edges_list)} edges. Removed {pruned_edges_count - len(archived_edges_list)} invalid edges.")
        return 0

    def decay_nodes(self, days_stale: int = 30) -> int:
        """Algorithmic forgetting (Ebbinghaus curve approximation).

        Archives nodes that haven't been accessed recently (per node_stats.json)
        AND are older than `days_stale`. Uses RelationPatchStore.deprecate_node
        for auditable, reversible status transitions.
        """
        from datetime import datetime as _dt, timedelta as _td, timezone as _timezone
        from memory_os.core.patch import RelationPatchStore, RelationPatch

        cutoff = (_dt.now(_timezone.utc) - _td(days=days_stale)).isoformat().replace("+00:00", "Z")

        stats_path = self.config.memory_dir / "node_stats.json"
        stats = NodeStatsStore(stats_path, self.storage).load()

        nodes_file = self.config.memory_dir / "nodes.jsonl"
        nodes = self._load_jsonl(nodes_file)

        stale_ids = []
        for n in nodes:
            if n.get("status") not in ("verified", "active", "draft"):
                continue
            if "pinned" in {str(tag) for tag in n.get("tags", [])}:
                continue
            valid_from = n.get("valid_from") or n.get("freshness", "")
            if not valid_from or valid_from >= cutoff:
                continue  # created recently — keep
            access_stat = stats.get(n["id"])
            last_accessed = access_stat.last_accessed if access_stat else ""
            if last_accessed and last_accessed >= cutoff:
                continue  # accessed recently — keep
            stale_ids.append(n["id"])

        if not stale_ids:
            return 0

        patch_store = RelationPatchStore(self.repository)
        archived_count = 0
        for nid in stale_ids:
            patch = RelationPatch(
                operation="deprecate_node",
                source=nid,
                target=nid,
                type="fact",
                domain="",
                confidence=0.0,
                evidence=[],
                reason=f"Algorithmic decay: not accessed in >{days_stale} days (cutoff {cutoff}).",
                created_by_protocol=0,
                required_verification_protocol=0,
            )
            try:
                patch_store.propose(patch)
                patch_store.apply(patch.id)
                archived_count += 1
            except Exception as exc:
                logger.warning(f"[decay_nodes] Failed to archive {nid}: {exc}")

        logger.info(f"[decay_nodes] Archived {archived_count} nodes (days_stale={days_stale}).")
        return archived_count
