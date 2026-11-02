from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional, Set

from memory_os.core.config import MemoryOSConfig
from memory_os.core.patch import RelationPatch, RelationPatchStore
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.timecode import now_local_iso, parse_timecode, user_timezone
from memory_os.modules.search import MemorySearcher
from memory_os.toolkit.eval_runner import EvalRunner

INACTIVE_NODE_STATUSES = {"archived", "stale", "superseded"}


class MemoryGraphService:
    def __init__(
        self,
        config: Optional[MemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None,
        searcher: Optional[MemorySearcher] = None,
    ):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(self.storage, self.config)
        self.searcher = searcher or MemorySearcher(self.config, repository=self.repository)

    @staticmethod
    def _as_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(value)]

    @staticmethod
    def _bounded_int(value: Any, default: int, floor: int = 0, ceiling: int = 500) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(floor, min(ceiling, parsed))

    def _apply_graph_patch(self, patch: RelationPatch, events: Optional[List[Dict[str, Any]]] = None) -> tuple[bool, str]:
        store = RelationPatchStore(self.repository)
        patch_id = store.propose(patch)
        return store.apply(patch_id, events=events), patch_id

    def _apply_graph_patches(self, patches: List[RelationPatch], events: Optional[List[Dict[str, Any]]] = None) -> tuple[bool, List[str]]:
        store = RelationPatchStore(self.repository)
        patch_ids = [store.propose(patch) for patch in patches]
        return store.apply_many(patch_ids, events=events), patch_ids

    def _load_local_nodes(self) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(self.config.memory_dir / "nodes.jsonl")

    def _load_local_edges(self) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(self.config.memory_dir / "edges.jsonl")

    def _find_local_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        for node in self._load_local_nodes():
            if str(node.get("id", "")) == node_id:
                return node
        return None

    def _event(self, name: str, node_id: str, claim: str, evidence: Optional[List[str]] = None, **extra: Any) -> Dict[str, Any]:
        event = {
            "timestamp": now_local_iso(self.config),
            "event": name,
            "node_id": node_id,
            "claim": claim,
            "evidence": evidence or [],
            "validator": "memory_graph_service",
            "status": "accepted",
        }
        event.update(extra)
        return event

    def export_graph(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "nodes": self._load_local_nodes(),
            "edges": self._load_local_edges(),
        }

    def timeline(self, days: int = 30, node_type: str = "", status: str = "") -> Dict[str, Any]:
        nodes = self._load_local_nodes()
        tz = user_timezone(self.config)
        now = datetime.now(tz).replace(microsecond=0)
        days = self._bounded_int(days, 30, floor=1, ceiling=3660)
        cutoff = now - timedelta(days=days)
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for node in nodes:
            if node.get("status") in INACTIVE_NODE_STATUSES:
                continue
            if node_type and str(node.get("type", "")) != node_type:
                continue
            if status and str(node.get("status", "")) != status:
                continue

            ts = None
            for key in ("updated_at", "created_at", "freshness", "valid_from", "last_accessed"):
                parsed = parse_timecode(node.get(key), assume_tz=timezone.utc)
                if parsed is not None:
                    ts = parsed.astimezone(tz).replace(microsecond=0)
                    break
            if ts is None or ts < cutoff:
                continue

            grouped[ts.date().isoformat()].append({
                "id": str(node.get("id", "")),
                "type": str(node.get("type", "")),
                "status": str(node.get("status", "")),
                "summary": str(node.get("summary", "")),
                "tags": self._as_list(node.get("tags")),
                "ts": ts.isoformat(timespec="seconds"),
            })

        days_payload = []
        for date_key in sorted(grouped.keys(), reverse=True):
            day_nodes = sorted(grouped[date_key], key=lambda item: item["ts"], reverse=True)
            days_payload.append({"date": date_key, "nodes": day_nodes})
        return {"status": "ok", "days": days_payload}

    def list_nodes(
        self,
        query: str = "",
        node_type: str = "",
        status: str = "",
        trust: str = "",
        tag: str = "",
        since: str = "",
        include_internal: bool = False,
        limit: Optional[int] = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        nodes = self._load_local_nodes()
        if include_internal:
            nodes.extend(self.storage.load_jsonl(self.config.internal_memory_dir / "nodes.jsonl"))
        query_l = query.strip().lower()
        tag_l = tag.strip().lower()

        def matches(node: Dict[str, Any]) -> bool:
            if node_type and str(node.get("type", "")) != node_type:
                return False
            if status and str(node.get("status", "")) != status:
                return False
            if trust and str(node.get("trust", "")) != trust:
                return False
            if tag_l and tag_l not in {str(t).lower() for t in node.get("tags", [])}:
                return False
            if since and str(node.get("freshness", "")) < since:
                return False
            if query_l:
                text = " ".join([
                    str(node.get("id", "")),
                    str(node.get("summary", "")),
                    " ".join(str(t) for t in node.get("tags", [])),
                    " ".join(str(e) for e in node.get("evidence", [])),
                ]).lower()
                return query_l in text
            return True

        filtered = [node for node in nodes if matches(node)]
        offset = self._bounded_int(offset, 0, floor=0, ceiling=max(0, len(filtered)))
        bounded_limit = None if limit is None else self._bounded_int(limit, 100, floor=1, ceiling=500)
        return {
            "status": "ok",
            "total": len(filtered),
            "limit": bounded_limit,
            "offset": offset,
            "nodes": filtered[offset:] if bounded_limit is None else filtered[offset: offset + bounded_limit],
        }

    def get_node(self, node_id: str) -> Dict[str, Any]:
        nodes = self._load_local_nodes()
        edges = self._load_local_edges()
        for node in nodes:
            if str(node.get("id", "")) == node_id:
                return {
                    "status": "ok",
                    "node": node,
                    "edges": [
                        edge for edge in edges
                        if edge.get("source") == node_id or edge.get("target") == node_id
                    ],
                }
        return {"status": "not_found", "node": None, "edges": []}

    def upsert_node(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = dict(payload.get("node") or payload)
        node_id = str(raw.get("id", "")).strip()
        summary = str(raw.get("summary", "")).strip()
        if not node_id:
            raise ValueError("node id is required")
        if not summary:
            raise ValueError("node summary is required")

        now = now_local_iso(self.config)
        raw["id"] = node_id
        raw["summary"] = summary
        raw["type"] = str(raw.get("type") or "fact")
        raw["status"] = str(raw.get("status") or "draft")
        raw["trust"] = str(raw.get("trust") or "unverified")
        raw["freshness"] = str(raw.get("freshness") or now)
        raw["evidence"] = self._as_list(raw.get("evidence"))
        raw["tags"] = self._as_list(raw.get("tags"))
        raw["related_nodes"] = self._as_list(raw.get("related_nodes"))
        raw["confidence"] = float(raw.get("confidence", 1.0) or 1.0)
        raw.setdefault("indexable", True)

        self.repository.upsert_node(raw, events=[{
            "timestamp": now,
            "event": "memory.ui.node.upserted",
            "node_id": node_id,
            "claim": f"UI memory API upserted node {node_id}",
            "evidence": raw.get("evidence", []),
            "validator": "memory_graph_service",
            "status": "accepted",
        }])
        return self.get_node(node_id)

    def update_node(self, node_id: str, summary: Optional[str] = None, tags: Any = None) -> Dict[str, Any]:
        node_id = str(node_id or "").strip()
        if not node_id:
            raise ValueError("node id is required")
        if self._find_local_node(node_id) is None:
            return {"status": "not_found", "node_id": node_id, "updated": False}

        updates: Dict[str, Any] = {"freshness": now_local_iso(self.config)}
        if summary is not None:
            updates["summary"] = str(summary).strip()
        if tags is not None:
            updates["tags"] = self._as_list(tags)
        if set(updates.keys()) == {"freshness"}:
            raise ValueError("summary or tags are required")

        applied = self.repository.update_node(
            node_id,
            updates,
            events=[self._event(
                "memory.ui.node.updated",
                node_id,
                f"UI memory API updated node {node_id}",
            )],
        )
        if not applied:
            return {"status": "not_found", "node_id": node_id, "updated": False}
        result = self.get_node(node_id)
        result["updated"] = True
        return result

    def verify_node(self, node_id: str) -> Dict[str, Any]:
        node_id = str(node_id or "").strip()
        if not node_id:
            raise ValueError("node id is required")
        if self._find_local_node(node_id) is None:
            return {"status": "not_found", "node_id": node_id, "verified": False}

        now = now_local_iso(self.config)
        applied = self.repository.update_node(
            node_id,
            {"trust": "verified", "protocol_level": 99, "freshness": now},
            events=[self._event(
                "memory.ui.node.verified",
                node_id,
                f"UI memory API verified node {node_id}",
            )],
        )
        return {"status": "ok" if applied else "not_found", "node_id": node_id, "verified": bool(applied)}

    def pin_node(self, node_id: str, pinned: bool) -> Dict[str, Any]:
        node_id = str(node_id or "").strip()
        if not node_id:
            raise ValueError("node id is required")
        node = self._find_local_node(node_id)
        if node is None:
            return {"status": "not_found", "node_id": node_id, "pinned": False}

        tags = [tag for tag in self._as_list(node.get("tags")) if tag != "pinned"]
        if bool(pinned):
            tags.append("pinned")
        now = now_local_iso(self.config)
        applied = self.repository.update_node(
            node_id,
            {"tags": tags, "freshness": now},
            events=[self._event(
                "memory.ui.node.pinned",
                node_id,
                f"UI memory API set pinned={bool(pinned)} for node {node_id}",
                pinned=bool(pinned),
            )],
        )
        if not applied:
            return {"status": "not_found", "node_id": node_id, "pinned": False}
        result = self.get_node(node_id)
        result["pinned"] = bool(pinned)
        return result

    def archive_node(self, node_id: str, reason: str = "") -> Dict[str, Any]:
        if self.get_node(node_id)["status"] != "ok":
            return {"status": "not_found", "node_id": node_id, "archived": False}

        now = now_local_iso(self.config)
        applied = self.repository.update_node(
            node_id,
            {"status": "archived", "valid_until": now, "freshness": now},
            events=[{
                "timestamp": now,
                "event": "memory.ui.node.archived",
                "node_id": node_id,
                "claim": reason or f"UI memory API archived node {node_id}",
                "evidence": [],
                "validator": "memory_graph_service",
                "status": "accepted",
            }],
        )
        return {"status": "ok" if applied else "error", "node_id": node_id, "archived": bool(applied)}

    def delete_node(self, node_id: str) -> Dict[str, Any]:
        node_id = str(node_id or "").strip()
        if not node_id:
            raise ValueError("node id is required")

        nodes = self._load_local_nodes()
        edges = self._load_local_edges()
        node = next((n for n in nodes if str(n.get("id", "")) == node_id), None)
        if node is None:
            return {"status": "not_found", "node_id": node_id, "deleted": False, "deleted_edges": 0}

        remaining_nodes = [n for n in nodes if str(n.get("id", "")) != node_id]
        remaining_edges = [
            edge for edge in edges
            if str(edge.get("source", "")) != node_id and str(edge.get("target", "")) != node_id
        ]
        deleted_edges = len(edges) - len(remaining_edges)
        node_patch = self.repository._make_patch(
            operation="replace_nodes",
            target="memory/nodes.jsonl",
            payload={"nodes": remaining_nodes},
            reason=f"UI memory API deleted node {node_id}",
        )
        edge_patch = self.repository._make_patch(
            operation="replace_edges",
            target="memory/edges.jsonl",
            payload={"edges": remaining_edges},
            reason=f"UI memory API deleted incident edges for {node_id}",
        )
        applied, patch_ids = self._apply_graph_patches(
            [node_patch, edge_patch],
            events=[self._event(
                "memory.ui.node.deleted",
                node_id,
                f"UI memory API deleted node {node_id} and {deleted_edges} incident edge(s)",
                evidence=self._as_list(node.get("evidence")),
                deleted_edges=deleted_edges,
            )],
        )
        return {
            "status": "ok" if applied else "error",
            "node_id": node_id,
            "deleted": bool(applied),
            "deleted_edges": deleted_edges if applied else 0,
            "patch_ids": patch_ids,
        }

    def merge_nodes(self, source_id: str, target_id: str) -> Dict[str, Any]:
        source_id = str(source_id or "").strip()
        target_id = str(target_id or "").strip()
        if not source_id or not target_id:
            raise ValueError("source and target are required")
        if source_id == target_id:
            raise ValueError("source and target must differ")

        nodes = self._load_local_nodes()
        edges = self._load_local_edges()
        source_node = next((n for n in nodes if str(n.get("id", "")) == source_id), None)
        target_node = next((n for n in nodes if str(n.get("id", "")) == target_id), None)
        if source_node is None or target_node is None:
            return {
                "status": "not_found",
                "merged": False,
                "source": source_id,
                "target": target_id,
            }

        now = now_local_iso(self.config)
        merged_target = dict(target_node)
        merged_target["evidence"] = sorted(set(self._as_list(target_node.get("evidence")) + self._as_list(source_node.get("evidence"))))
        merged_target["tags"] = sorted(set(self._as_list(target_node.get("tags")) + self._as_list(source_node.get("tags"))))
        source_summary = str(source_node.get("summary", "")).strip()
        target_summary = str(target_node.get("summary", "")).strip()
        if source_summary and source_summary not in target_summary:
            merged_target["summary"] = f"{target_summary} | Merged from: {source_summary}" if target_summary else source_summary
        merged_target["freshness"] = now

        new_nodes = []
        for node in nodes:
            node_id = str(node.get("id", ""))
            if node_id == source_id:
                continue
            if node_id == target_id:
                new_nodes.append(merged_target)
            else:
                new_nodes.append(node)

        new_edges = []
        seen = set()
        for edge in edges:
            rewired = dict(edge)
            if str(rewired.get("source", "")) == source_id:
                rewired["source"] = target_id
            if str(rewired.get("target", "")) == source_id:
                rewired["target"] = target_id
            if rewired.get("source") == rewired.get("target"):
                continue
            key = (rewired.get("source"), rewired.get("target"), rewired.get("type"))
            if key in seen:
                continue
            seen.add(key)
            new_edges.append(rewired)

        node_patch = self.repository._make_patch(
            operation="replace_nodes",
            target="memory/nodes.jsonl",
            payload={"nodes": new_nodes},
            reason=f"UI memory API merged node {source_id} into {target_id}",
        )
        edge_patch = self.repository._make_patch(
            operation="replace_edges",
            target="memory/edges.jsonl",
            payload={"edges": new_edges},
            reason=f"UI memory API rewired merge edges {source_id}->{target_id}",
        )
        applied, patch_ids = self._apply_graph_patches(
            [node_patch, edge_patch],
            events=[self._event(
                "memory.ui.node.merged",
                target_id,
                f"UI memory API merged {source_id} into {target_id}",
                evidence=merged_target.get("evidence", []),
                source_id=source_id,
                target_id=target_id,
            )],
        )
        return {
            "status": "ok" if applied else "error",
            "merged": bool(applied),
            "source": source_id,
            "target": target_id,
            "patch_ids": patch_ids,
        }

    def list_edges(
        self,
        source: str = "",
        target: str = "",
        edge_type: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        edges = self._load_local_edges()
        filtered = [
            edge for edge in edges
            if (not source or edge.get("source") == source)
            and (not target or edge.get("target") == target)
            and (not edge_type or edge.get("type") == edge_type)
        ]
        limit = self._bounded_int(limit, 100, floor=1, ceiling=500)
        offset = self._bounded_int(offset, 0, floor=0, ceiling=max(0, len(filtered)))
        return {
            "status": "ok",
            "total": len(filtered),
            "limit": limit,
            "offset": offset,
            "edges": filtered[offset: offset + limit],
        }

    def upsert_edge(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        raw = dict(payload.get("edge") or payload)
        source = str(raw.get("source", "")).strip()
        target = str(raw.get("target", "")).strip()
        edge_type = str(raw.get("type", "") or "depends_on").strip()
        if not source or not target:
            raise ValueError("edge source and target are required")
        if not edge_type:
            raise ValueError("edge type is required")

        raw["source"] = source
        raw["target"] = target
        raw["type"] = edge_type
        raw["evidence"] = self._as_list(raw.get("evidence"))
        raw["confidence"] = float(raw.get("confidence", 1.0) or 1.0)
        raw.setdefault("reason", "UI memory API upsert")

        now = now_local_iso(self.config)
        self.repository.upsert_edge(raw, events=[{
            "timestamp": now,
            "event": "memory.ui.edge.upserted",
            "node_id": target,
            "claim": f"UI memory API upserted edge {source}->{target}",
            "evidence": raw.get("evidence", []),
            "validator": "memory_graph_service",
            "status": "accepted",
        }])
        return {"status": "ok", "edge": raw}

    def delete_edge(self, source: str, target: str, edge_type: str) -> Dict[str, Any]:
        source = str(source or "").strip()
        target = str(target or "").strip()
        edge_type = str(edge_type or "").strip()
        if not source or not target or not edge_type:
            raise ValueError("edge source, target, and type are required")

        created_by_protocol, required_verification_protocol = self.repository._edge_protocols(edge_type, None)
        patch = RelationPatch(
            operation="delete_edge_soft",
            source=source,
            target=target,
            type=edge_type,
            domain="memory_graph",
            confidence=1.0,
            evidence=[],
            reason=f"UI memory API deleted edge {source}->{target}",
            created_by_protocol=created_by_protocol,
            required_verification_protocol=required_verification_protocol,
        )
        now = now_local_iso(self.config)
        store = RelationPatchStore(self.repository)
        patch_id = store.propose(patch)
        applied = store.apply(patch_id, events=[{
            "timestamp": now,
            "event": "memory.ui.edge.deleted",
            "node_id": target,
            "claim": f"UI memory API deleted edge {source}->{target}",
            "evidence": [],
            "validator": "memory_graph_service",
            "status": "accepted",
        }])
        return {"status": "ok" if applied else "not_found", "deleted": bool(applied), "patch_id": patch_id}

    def list_events(self, node_id: str = "", limit: int = 50) -> Dict[str, Any]:
        events = self.storage.load_jsonl(self.config.memory_dir / "events.jsonl")
        if node_id:
            events = [event for event in events if str(event.get("node_id", "")) == node_id]
        limit = self._bounded_int(limit, 50, floor=1, ceiling=500)
        return {
            "status": "ok",
            "total": len(events),
            "limit": limit,
            "events": events[-limit:],
        }

    def health(self) -> Dict[str, Any]:
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        edges_path = self.config.memory_dir / "edges.jsonl"
        archived_nodes_path = self.config.memory_dir / "archived_nodes.jsonl"
        archived_edges_path = self.config.memory_dir / "archived_edges.jsonl"

        nodes = self.storage.load_jsonl(nodes_path)
        edges = self.storage.load_jsonl(edges_path)
        archived_nodes = self.storage.load_jsonl(archived_nodes_path) if self.storage.exists(archived_nodes_path) else []
        archived_edges = self.storage.load_jsonl(archived_edges_path) if self.storage.exists(archived_edges_path) else []

        node_ids = {str(n.get("id", "")) for n in nodes if n.get("id")}
        degree = defaultdict(int)
        incident = set()
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in node_ids:
                degree[source] += 1
                incident.add(source)
            if target in node_ids:
                degree[target] += 1
                incident.add(target)

        orphan_nodes = [n for n in nodes if str(n.get("id", "")) not in incident]
        comm_nodes = [n for n in nodes if str(n.get("id", "")).startswith("comm:")]
        low_confidence_floor = 0.5
        low_confidence_nodes = [
            str(n.get("id", ""))
            for n in nodes
            if float(n.get("confidence", 1.0) or 1.0) < low_confidence_floor
        ]
        comm_noise_ratio = round(len(comm_nodes) / max(1, len(nodes)), 3)
        edge_density = round(len(edges) / max(1, len(nodes)), 3)
        orphan_ratio = round(len(orphan_nodes) / max(1, len(nodes)), 3)

        top_connected = sorted(
            (n for n in nodes if n.get("id")),
            key=lambda n: (degree[str(n["id"])], str(n["id"])),
            reverse=True,
        )[:5]

        eval_result = None
        try:
            runner = EvalRunner(self.config)
            suites = runner.list_suites()
            if any(s.get("name") == "retrieval-relevance" for s in suites):
                eval_result = runner.run("retrieval-relevance")
        except Exception:
            eval_result = None

        eval_available = eval_result is not None
        eval_ok = bool(eval_result and eval_result.get("ok"))
        if not nodes:
            status = "red"
        elif eval_result is False or (eval_available and not eval_ok):
            status = "red"
        elif not eval_available:
            status = "yellow"
        elif comm_noise_ratio > 0.6 or orphan_ratio > 0.5:
            status = "yellow"
        else:
            status = "green"

        return {
            "status": status,
            "live_nodes": len(nodes),
            "live_edges": len(edges),
            "archived_nodes": len(archived_nodes),
            "archived_edges": len(archived_edges),
            "comm_nodes": len(comm_nodes),
            "comm_noise_ratio": comm_noise_ratio,
            "orphan_nodes": [str(n.get("id", "")) for n in orphan_nodes[:10]],
            "orphan_ratio": orphan_ratio,
            "edge_density": edge_density,
            "confidence_floor": low_confidence_floor,
            "low_confidence_nodes": low_confidence_nodes[:10],
            "low_confidence_count": len(low_confidence_nodes),
            "top_connected_nodes": [
                {
                    "id": str(n.get("id", "")),
                    "degree": degree[str(n["id"])],
                    "summary": str(n.get("summary", ""))[:120],
                }
                for n in top_connected
            ],
            "eval_status": "ok" if eval_ok else ("unavailable" if not eval_available else "failed"),
            "eval": eval_result or {
                "suite": "retrieval-relevance",
                "status": "skipped",
                "reason": "suite unavailable or eval runner failed",
            },
        }

    def curate(self, limit: int = 10) -> Dict[str, Any]:
        nodes = self.storage.load_jsonl(self.config.memory_dir / "nodes.jsonl")
        edges = self.storage.load_jsonl(self.config.memory_dir / "edges.jsonl")

        def tokenize(text: str) -> set[str]:
            return {tok for tok in re.split(r"\W+", text.lower()) if len(tok) >= 4}

        def pair_score(left: dict, right: dict) -> tuple[float, list[str]]:
            reasons: list[str] = []
            score = 0.0
            if left.get("type") == right.get("type"):
                score += 0.2
                reasons.append("same-type")

            left_tags = {str(tag).lower() for tag in left.get("tags", []) if str(tag).strip()}
            right_tags = {str(tag).lower() for tag in right.get("tags", []) if str(tag).strip()}
            shared_tags = sorted(tag for tag in (left_tags & right_tags) if not tag.startswith("comm"))
            if shared_tags:
                score += min(0.35, 0.12 * len(shared_tags))
                reasons.append(f"shared-tags:{','.join(shared_tags[:3])}")

            left_tokens = tokenize(str(left.get("summary", "")))
            right_tokens = tokenize(str(right.get("summary", "")))
            if left_tokens and right_tokens:
                overlap = left_tokens & right_tokens
                union = left_tokens | right_tokens
                token_score = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))
                if token_score:
                    score += min(0.55, token_score * 0.55)
                    reasons.append(f"summary-overlap:{len(overlap)}/{len(union)}")

            left_evidence = {str(p) for p in left.get("evidence", [])}
            right_evidence = {str(p) for p in right.get("evidence", [])}
            shared_evidence = left_evidence & right_evidence
            if shared_evidence:
                score += min(0.25, 0.15 * len(shared_evidence))
                reasons.append("shared-evidence")

            left_id = str(left.get("id", ""))
            right_id = str(right.get("id", ""))
            if left_id and right_id:
                left_parts = [part for part in re.split(r"[._\-/]", left_id) if part]
                right_parts = [part for part in re.split(r"[._\-/]", right_id) if part]
                if left_parts and right_parts:
                    short, long = (left_parts, right_parts) if len(left_parts) <= len(right_parts) else (right_parts, left_parts)
                    if long[: len(short)] == short:
                        score += 0.15
                        reasons.append("id-prefix")

            return round(min(score, 1.0), 3), reasons

        node_map = {str(node.get("id", "")): node for node in nodes if node.get("id")}
        node_ids = list(node_map)
        node_ids_set = set(node_ids)
        incident = defaultdict(int)
        adjacency = defaultdict(set)
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in node_ids_set and target in node_ids_set:
                incident[source] += 1
                incident[target] += 1
                adjacency[source].add(target)
                adjacency[target].add(source)

        orphans = [nid for nid in node_ids if incident[nid] == 0 and not nid.startswith("comm:")]
        merge_candidates = []
        seen_pairs = set()
        for i, left_id in enumerate(node_ids):
            left = node_map[left_id]
            if left_id.startswith("comm:"):
                continue
            for right_id in node_ids[i + 1:]:
                right = node_map[right_id]
                if right_id.startswith("comm:"):
                    continue
                if left.get("status") in {"archived", "superseded"} or right.get("status") in {"archived", "superseded"}:
                    continue
                if (left_id, right_id) in seen_pairs or (right_id, left_id) in seen_pairs:
                    continue
                if right_id in adjacency[left_id]:
                    continue
                score, reasons = pair_score(left, right)
                if score < 0.65:
                    continue
                seen_pairs.add((left_id, right_id))
                merge_candidates.append({
                    "left": left_id,
                    "right": right_id,
                    "score": score,
                    "reasons": reasons,
                })

        merge_candidates.sort(key=lambda item: (-item["score"], item["left"], item["right"]))

        components = []
        visited = set()
        for start in node_ids:
            if start in visited:
                continue
            queue = deque([start])
            visited.add(start)
            component = []
            while queue:
                current = queue.popleft()
                component.append(current)
                for nxt in sorted(adjacency[current]):
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
            if len(component) > 1:
                component_edges = sum(1 for edge in edges if str(edge.get("source", "")) in component and str(edge.get("target", "")) in component)
                density = round(component_edges / max(1, len(component)), 3)
                components.append({
                    "size": len(component),
                    "density": density,
                    "nodes": component,
                })

        components.sort(key=lambda item: (-item["size"], -item["density"], item["nodes"][0]))
        if limit:
            merge_candidates = merge_candidates[: limit]
            components = components[: limit]

        comm_nodes = [nid for nid in node_ids if nid.startswith("comm:")]
        next_actions: list[dict[str, Any]] = []
        if merge_candidates:
            top_candidate = merge_candidates[0]
            next_actions.append({
                "action": "merge-preview",
                "reason": f"Top merge candidate {top_candidate['left']} <-> {top_candidate['right']} (score {top_candidate['score']:.2f})",
                "priority": "high",
            })
            next_actions.append({
                "action": "merge-apply",
                "reason": "Apply semantic merge after review",
                "priority": "medium",
            })
        if orphans:
            next_actions.append({
                "action": "browse",
                "reason": f"{len(orphans)} orphan node(s) need link review",
                "priority": "medium",
            })
        if comm_nodes:
            next_actions.append({
                "action": "health",
                "reason": f"{len(comm_nodes)} comm node(s) remain noisy",
                "priority": "low",
            })

        primary_recommendation = next_actions[0]["action"] if next_actions else "none"
        return {
            "status": "yellow" if orphans or merge_candidates else "green",
            "live_nodes": len(node_ids),
            "live_edges": len(edges),
            "orphan_nodes": orphans[:20],
            "merge_candidates": merge_candidates,
            "components": components[:10],
            "comm_nodes": len(comm_nodes),
            "primary_recommendation": primary_recommendation,
            "next_actions": next_actions[:5],
        }

    def merge_preview(self, limit: int = 10) -> Dict[str, Any]:
        nodes = self.storage.load_jsonl(self.config.memory_dir / "nodes.jsonl")
        edges = self.storage.load_jsonl(self.config.memory_dir / "edges.jsonl")

        def normalize(text: str) -> str:
            return " ".join(re.split(r"\W+", text.lower())).strip()

        def score_pair(left: dict, right: dict) -> tuple[float, list[str]]:
            reasons: list[str] = []
            score = 0.0
            if left.get("type") == right.get("type"):
                score += 0.15
                reasons.append("same-type")

            left_summary = normalize(str(left.get("summary", "")))
            right_summary = normalize(str(right.get("summary", "")))
            if left_summary and right_summary:
                left_tokens = set(left_summary.split())
                right_tokens = set(right_summary.split())
                overlap = left_tokens & right_tokens
                if overlap:
                    overlap_ratio = len(overlap) / max(1, min(len(left_tokens), len(right_tokens)))
                    score += min(0.5, overlap_ratio * 0.6)
                    reasons.append(f"summary-overlap:{len(overlap)}")

            left_tags = {str(tag).lower() for tag in left.get("tags", []) if str(tag).strip()}
            right_tags = {str(tag).lower() for tag in right.get("tags", []) if str(tag).strip()}
            shared_tags = sorted(tag for tag in (left_tags & right_tags) if not tag.startswith("comm"))
            if shared_tags:
                score += min(0.25, 0.08 * len(shared_tags))
                reasons.append(f"shared-tags:{','.join(shared_tags[:3])}")

            left_evidence = {str(p) for p in left.get("evidence", [])}
            right_evidence = {str(p) for p in right.get("evidence", [])}
            shared_evidence = left_evidence & right_evidence
            if shared_evidence:
                score += min(0.25, 0.12 * len(shared_evidence))
                reasons.append("shared-evidence")

            left_id = str(left.get("id", ""))
            right_id = str(right.get("id", ""))
            if left_id and right_id:
                if normalize(left_id) == normalize(right_id):
                    score += 0.6
                    reasons.append("normalized-id-match")
                else:
                    left_parts = [part for part in re.split(r"[._\-/]", left_id) if part]
                    right_parts = [part for part in re.split(r"[._\-/]", right_id) if part]
                    if left_parts and right_parts:
                        short, long = (left_parts, right_parts) if len(left_parts) <= len(right_parts) else (right_parts, left_parts)
                        if long[: len(short)] == short:
                            score += 0.12
                            reasons.append("id-prefix")

            return round(min(score, 1.0), 3), reasons

        def rank_node(node: dict, degree: int) -> tuple:
            status_rank = {
                "verified": 4,
                "observed": 3,
                "draft": 2,
                "stale": 1,
                "superseded": 0,
                "archived": -1,
            }.get(str(node.get("status", "draft")), 2)
            trust_rank = {
                "verified": 4,
                "inferred": 3,
                "extracted": 2,
                "unverified": 1,
                "system": 0,
            }.get(str(node.get("trust", "unverified")), 1)
            freshness = str(node.get("freshness", ""))
            return (
                status_rank,
                trust_rank,
                degree,
                len(str(node.get("summary", ""))),
                freshness,
                str(node.get("id", "")),
            )

        node_map = {str(node.get("id", "")): node for node in nodes if node.get("id")}
        node_ids = list(node_map)
        node_ids_set = set(node_ids)
        degree = defaultdict(int)
        adjacency = defaultdict(set)
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in node_ids_set and target in node_ids_set:
                degree[source] += 1
                degree[target] += 1
                adjacency[source].add(target)
                adjacency[target].add(source)

        candidate_graph = defaultdict(set)
        candidate_pairs = []
        for i, left_id in enumerate(node_ids):
            left = node_map[left_id]
            if left_id.startswith("comm:"):
                continue
            for right_id in node_ids[i + 1:]:
                right = node_map[right_id]
                if right_id.startswith("comm:"):
                    continue
                if left.get("status") in {"archived", "superseded"} or right.get("status") in {"archived", "superseded"}:
                    continue
                if right_id in adjacency[left_id]:
                    continue
                score, reasons = score_pair(left, right)
                if score < 0.72:
                    continue
                candidate_graph[left_id].add(right_id)
                candidate_graph[right_id].add(left_id)
                candidate_pairs.append({
                    "left": left_id,
                    "right": right_id,
                    "score": score,
                    "reasons": reasons,
                })

        candidate_pairs.sort(key=lambda item: (-item["score"], item["left"], item["right"]))

        seen = set()
        groups = []
        for start in node_ids:
            if start in seen or start not in candidate_graph:
                continue
            queue = deque([start])
            seen.add(start)
            group_ids = []
            while queue:
                current = queue.popleft()
                group_ids.append(current)
                for nxt in sorted(candidate_graph[current]):
                    if nxt not in seen:
                        seen.add(nxt)
                        queue.append(nxt)
            if len(group_ids) < 2:
                continue
            members = [node_map[nid] for nid in group_ids]
            canonical = max(members, key=lambda n: rank_node(n, degree[str(n["id"])]) )
            merged_tags = sorted({
                str(tag).lower()
                for node in members
                for tag in node.get("tags", [])
                if str(tag).strip()
            })
            merged_evidence = sorted({
                str(ev)
                for node in members
                for ev in node.get("evidence", [])
                if str(ev).strip()
            })
            group_summary_parts = [canonical.get("summary", "").strip()]
            for node in sorted(members, key=lambda n: str(n.get("id", ""))):
                summary = str(node.get("summary", "")).strip()
                if summary and summary != canonical.get("summary", "").strip():
                    group_summary_parts.append(summary)
            merged_summary = " / ".join(dict.fromkeys(group_summary_parts))[:360]
            groups.append({
                "canonical": canonical.get("id"),
                "members": sorted(group_ids),
                "size": len(group_ids),
                "canonical_status": canonical.get("status", "draft"),
                "canonical_trust": canonical.get("trust", "unverified"),
                "canonical_score": rank_node(canonical, degree[str(canonical.get("id"))]),
                "merged_summary": merged_summary,
                "merged_tags": merged_tags[:20],
                "merged_evidence": merged_evidence[:20],
                "replacement_plan": [
                    {
                        "keep": canonical.get("id"),
                        "replace": nid,
                        "relation": "overrides" if nid != canonical.get("id") else "canonical",
                    }
                    for nid in sorted(group_ids)
                ],
            })

        groups.sort(key=lambda item: (-item["size"], item["canonical"], item["members"][0]))
        if limit:
            groups = groups[:limit]

        return {
            "status": "ok" if groups else "empty",
            "live_nodes": len(node_ids),
            "live_edges": len(edges),
            "candidate_pairs": candidate_pairs[: min(len(candidate_pairs), max(10, limit * 3))],
            "merge_groups": groups,
        }

    def merge_apply(self, limit: int = 10, dry_run: bool = False) -> Dict[str, Any]:
        preview = self.merge_preview(limit=limit)
        if preview["status"] != "ok":
            return {
                **preview,
                "status": preview["status"],
                "applied": False,
                "patch_ids": [],
                "events": [],
                "applied_groups": 0,
                "merged_out_nodes": [],
            }

        nodes = [n.to_dict() for n in self.repository.get_nodes()]
        edges = [e.to_dict() for e in self.repository.get_edges()]
        node_map = {str(node.get("id", "")): dict(node) for node in nodes if node.get("id")}
        group_map = {group["canonical"]: group for group in preview["merge_groups"]}
        member_to_canonical = {
            member: canonical
            for canonical, group in group_map.items()
            for member in group["members"]
        }
        merge_member_ids = {
            nid
            for group in preview["merge_groups"]
            for nid in group["members"]
        }
        merged_out_nodes = sorted(
            nid
            for group in preview["merge_groups"]
            for nid in group["members"]
            if nid != group["canonical"]
        )

        def _merge_node_payload(canonical_id: str, members: List[str]) -> Dict[str, Any]:
            canonical = dict(node_map[canonical_id])
            member_nodes = [node_map[nid] for nid in members if nid in node_map]
            if not member_nodes:
                return canonical

            merged_tags = sorted({
                str(tag).lower()
                for node in member_nodes
                for tag in node.get("tags", [])
                if str(tag).strip()
            })
            merged_evidence = sorted({
                str(ev)
                for node in member_nodes
                for ev in node.get("evidence", [])
                if str(ev).strip()
            })
            summaries = [str(node.get("summary", "")).strip() for node in member_nodes if str(node.get("summary", "")).strip()]
            base_summary = str(canonical.get("summary", "")).strip()
            summary_parts = [base_summary] + [s for s in summaries if s and s != base_summary]
            merged_summary = " / ".join(dict.fromkeys(summary_parts))[:360]

            canonical["summary"] = merged_summary
            canonical["tags"] = merged_tags
            canonical["evidence"] = merged_evidence
            canonical["status"] = "verified"
            canonical["trust"] = "verified"
            canonical["freshness"] = member_nodes[0].get("freshness") or canonical.get("freshness") or ""
            canonical["confidence"] = max(float(node.get("confidence", 0.0) or 0.0) for node in member_nodes)
            if not canonical.get("related_nodes"):
                canonical["related_nodes"] = []
            canonical["related_nodes"] = sorted({
                str(nid)
                for node in member_nodes
                for nid in node.get("related_nodes", [])
                if str(nid).strip() and str(nid) not in members
            })
            return canonical

        new_nodes = []
        deprecation_events = []
        merge_events = []

        for node in nodes:
            node_id = str(node.get("id", ""))
            if not node_id:
                continue

            if node_id in group_map:
                merged = _merge_node_payload(node_id, group_map[node_id]["members"])
                merged["valid_from"] = node.get("valid_from") or merged.get("valid_from", "")
                new_nodes.append(merged)
                merge_events.append({
                    "timestamp": merged.get("freshness") or "",
                    "event": "memory.merge.canonicalized",
                    "node_id": node_id,
                    "claim": f"Canonicalized merge group for {node_id}",
                    "evidence": merged.get("evidence", []),
                    "validator": "memory_graph_service",
                    "status": "accepted",
                    "members": group_map[node_id]["members"],
                })
                continue

            if node_id in merge_member_ids:
                if node.get("status") not in {"superseded", "archived"}:
                    node = dict(node)
                    node["status"] = "superseded"
                    node["freshness"] = node.get("freshness") or ""
                    node["valid_until"] = node.get("valid_until") or node.get("freshness") or ""
                new_nodes.append(node)
                deprecation_events.append({
                    "timestamp": node.get("freshness") or "",
                    "event": "memory.node.merged_out",
                    "node_id": node_id,
                    "claim": f"Merged into canonical group",
                    "evidence": node.get("evidence", []),
                    "validator": "memory_graph_service",
                    "status": "accepted",
                })
                continue

            new_nodes.append(node)

        rewired_edges = []
        seen_edges = set()
        for edge in edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            if source in merge_member_ids:
                source = member_to_canonical.get(source, source)
            if target in merge_member_ids:
                target = member_to_canonical.get(target, target)
            if source == target:
                continue
            key = (source, target, edge.get("type", ""))
            if key in seen_edges:
                continue
            seen_edges.add(key)
            rewired_edge = dict(edge)
            rewired_edge["source"] = source
            rewired_edge["target"] = target
            rewired_edges.append(rewired_edge)

        patch_store = RelationPatchStore(self.repository)
        node_patch = RelationPatch(
            operation="replace_nodes",
            source="",
            target="memory/nodes.jsonl",
            type="fact",
            domain="memory_graph",
            confidence=1.0,
            evidence=[],
            reason="apply semantic merge groups to canonical nodes",
            created_by_protocol=0,
            required_verification_protocol=0,
            payload={"nodes": new_nodes},
        )
        edge_patch = RelationPatch(
            operation="replace_edges",
            source="",
            target="memory/edges.jsonl",
            type="fact",
            domain="memory_graph",
            confidence=1.0,
            evidence=[],
            reason="rewire edges after semantic merge groups",
            created_by_protocol=0,
            required_verification_protocol=0,
            payload={"edges": rewired_edges},
        )

        if dry_run:
            return {
                **preview,
                "applied": False,
                "patch_ids": [node_patch.id, edge_patch.id],
                "events": merge_events + deprecation_events,
                "applied_groups": len(preview["merge_groups"]),
                "merged_out_nodes": merged_out_nodes,
            }

        node_patch_id = patch_store.propose(node_patch)
        edge_patch_id = patch_store.propose(edge_patch)
        applied = patch_store.apply_many([node_patch_id, edge_patch_id], events=merge_events + deprecation_events)
        if not applied:
            return {
                **preview,
                "applied": False,
                "patch_ids": [node_patch_id, edge_patch_id],
                "events": merge_events + deprecation_events,
                "applied_groups": 0,
                "merged_out_nodes": merged_out_nodes,
            }

        return {
            **preview,
            "applied": True,
            "patch_ids": [node_patch_id, edge_patch_id],
            "events": merge_events + deprecation_events,
            "applied_groups": len(preview["merge_groups"]),
            "merged_out_nodes": merged_out_nodes,
        }

    def browse(
        self,
        query: str = "",
        node_id: Optional[str] = None,
        depth: int = 1,
        limit: int = 3,
        neighbors: int = 8,
        edges_limit: int = 12,
    ) -> Dict[str, Any]:
        nodes = self.repository.get_nodes()
        edges = self.repository.get_edges()
        nodes_by_id = {node.id: node for node in nodes if getattr(node, "id", None)}

        focus_ids: List[str] = []
        focus_query = query or node_id or ""
        if node_id:
            if node_id in nodes_by_id:
                focus_ids = [node_id]
            else:
                query_hits = [r for r in self.searcher.search_memory(node_id, depth=max(0, depth)) if r.get("type") != "code_file"]
                focus_ids = [str(r.get("id", "")) for r in query_hits if r.get("id")]
        elif focus_query:
            query_hits = [r for r in self.searcher.search_memory(focus_query, depth=max(0, depth)) if r.get("type") != "code_file"]
            focus_ids = [str(r.get("id", "")) for r in query_hits if r.get("id")]

        focus_ids = [nid for nid in focus_ids if nid in nodes_by_id][: max(1, limit)]
        if not focus_ids:
            return {
                "query": focus_query,
                "focus_ids": [],
                "results": [],
                "status": "not_found",
            }

        report = {
            "query": focus_query,
            "focus_ids": focus_ids,
            "results": [],
            "status": "ok",
        }

        for focus_id in focus_ids:
            focus = nodes_by_id[focus_id]
            inbound = [e for e in edges if e.target == focus_id]
            outbound = [e for e in edges if e.source == focus_id]
            related_ids = {str(nid) for nid in getattr(focus, "related_nodes", []) if str(nid)}
            focus_degree = len(inbound) + len(outbound)
            focus_status = str(getattr(focus, "status", "") or "")
            focus_trust = str(getattr(focus, "trust", "") or "")
            focus_reason_parts = []
            if focus_status in {"draft", "observed"}:
                focus_reason_parts.append(f"status={focus_status}")
            if focus_degree >= 2:
                focus_reason_parts.append(f"degree={focus_degree}")
            if inbound:
                focus_reason_parts.append(f"inbound={len(inbound)}")
            if outbound:
                focus_reason_parts.append(f"outbound={len(outbound)}")
            if related_ids:
                focus_reason_parts.append(f"related={len(related_ids)}")
            if focus_trust and focus_trust != "verified":
                focus_reason_parts.append(f"trust={focus_trust}")
            if not focus_reason_parts:
                focus_reason_parts.append("verified leaf or low-degree node")
            neighbor_ids = set().union(
                {e.source for e in inbound if e.source in nodes_by_id},
                {e.target for e in outbound if e.target in nodes_by_id},
                {nid for nid in related_ids if nid in nodes_by_id},
            )
            neighbor_ids.discard(focus_id)
            neighborhood_nodes = [nodes_by_id[nid].to_dict() for nid in sorted(neighbor_ids)[: neighbors]]
            neighborhood_edges = [
                e.to_dict()
                for e in edges
                if e.source in neighbor_ids | {focus_id} and e.target in neighbor_ids | {focus_id}
            ]
            report["results"].append({
                "focus": focus.to_dict(),
                "focus_signal": {
                    "degree": focus_degree,
                    "inbound": len(inbound),
                    "outbound": len(outbound),
                    "related": len(related_ids),
                    "reason": "; ".join(focus_reason_parts),
                },
                "inbound_edges": [e.to_dict() for e in inbound[: edges_limit]],
                "outbound_edges": [e.to_dict() for e in outbound[: edges_limit]],
                "related_node_ids": sorted(related_ids),
                "neighbor_nodes": neighborhood_nodes,
                "neighbor_edges": neighborhood_edges[: edges_limit],
            })

        return report

    def get_dedup_candidates(
        self,
        limit: Optional[int] = None,
        *,
        focus_ids: Optional[Set[str]] = None,
        candidate_status: str = "",
        include_all_types: bool = False,
        min_cosine: float = 0.9,
        min_jaccard: float = 0.8,
    ) -> List[Dict[str, Any]]:
        nodes = self.storage.load_jsonl(self.config.memory_dir / "nodes.jsonl")
        focus = set(focus_ids or [])
        filtered_nodes = [
            n for n in nodes
            if n.get("id")
            and (include_all_types or n.get("type") in {"fact", "rule"})
            and n.get("status") not in {"archived", "superseded"}
        ]
        
        from memory_os.toolkit.embedding_provider import EmbeddingProvider, _cosine
        provider = EmbeddingProvider(self.config)
        embeddings = provider._load_cache()
        
        def _tokens(s: str) -> frozenset:
            return frozenset(t for t in re.split(r"\W+", s.lower()) if t)

        def jaccard_similarity(toks1: frozenset, toks2: frozenset) -> float:
            if not toks1 and not toks2:
                return 1.0
            if not toks1 or not toks2:
                return 0.0
            return len(toks1 & toks2) / len(toks1 | toks2)

        # tokenize each summary once — O(n), not once per pair — O(n**2)
        token_sets = [_tokens(str(n.get("summary", ""))) for n in filtered_nodes]

        candidates = []
        for i, node_a in enumerate(filtered_nodes):
            nid_a = str(node_a["id"])
            for j, node_b in enumerate(filtered_nodes[i + 1:], start=i + 1):
                nid_b = str(node_b["id"])
                if focus:
                    a_to_b = nid_a in focus and (not candidate_status or node_b.get("status") == candidate_status)
                    b_to_a = nid_b in focus and (not candidate_status or node_a.get("status") == candidate_status)
                    if not (a_to_b or b_to_a):
                        continue

                jacc = jaccard_similarity(token_sets[i], token_sets[j])
                
                cosine = 0.0
                if nid_a in embeddings and nid_b in embeddings:
                    cosine = _cosine(embeddings[nid_a], embeddings[nid_b])
                    
                if cosine >= min_cosine or jacc >= min_jaccard:
                    candidates.append({
                        "node_a_id": nid_a,
                        "node_b_id": nid_b,
                        "cosine": round(cosine, 4),
                        "jaccard": round(jacc, 4),
                        "node_a": node_a,
                        "node_b": node_b,
                    })
                    
        candidates.sort(key=lambda c: (-max(c["cosine"], c["jaccard"]), c["node_a_id"], c["node_b_id"]))
        if limit:
            candidates = candidates[:limit]
        return candidates
