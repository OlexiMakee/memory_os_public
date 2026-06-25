from memory_os.core.logger import get_logger
logger = get_logger(__name__)
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Any, Optional

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from memory_os.core.interfaces import IMemoryOSConfig, IMemoryStorage, ILlmProviderService
from memory_os.core.repository import MemoryRepository
from memory_os.core.models import MemoryNode, MemoryEdge, NodeType, EdgeType
from memory_os.core.exceptions import MemoryOSError, ValidationError
from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.llm_service import DefaultLlmProviderService
from memory_os.core.scheduler import HardwareScheduler
from memory_os.modules.validator import EvolutionGate, VALID_EDGE_TYPES
from memory_os.modules.exporter import PolyglotExporter

SYSTEM_PROMPT = """You are the Memory OS Knowledge Compactor.
Your job is to analyze developer task logs (task capsules) and existing memory nodes, then extract new permanent knowledge nodes (rules, facts, configurations, or policies) and relationships (edges).

Guidelines for Nodes:
1. Extract only durable, architectural, or structural findings. Avoid documenting temporary issues.
2. Group lessons under namespace IDs, e.g., 'provider.openrouter.free_only', 'solid.srp.agent_service', etc.
3. Every node must have:
   - id: unique string namespace id (must match standard namespacing, lowercase, dot-separated).
   - type: one of "rule", "fact", "variable", "connector", "config", "policy".
   - summary: concise summary of the rule/fact/config/policy.
   - evidence: list of file paths that were modified or verified for this node.
4. If a node already exists (matches one of the provided existing node IDs), do not propose a new node under that ID unless you are revising its summary, in which case you must also output an "overrides" edge.

Guidelines for Edges:
1. Create edges between nodes to represent relationships.
2. Every edge must have:
   - source: node ID.
   - target: node ID.
   - type: one of "depends_on", "triggers", "refutes", "overrides", "configures", "secures".

Your output must be ONLY a raw JSON block with the following schema:
{
  "nodes": [
    {
      "id": "node.id.string",
      "type": "rule|fact|variable|connector|config|policy",
      "summary": "Concise lesson details.",
      "evidence": ["relative/file/path.py"],
      "tags": ["optional", "labels"],
      "globs": ["optional", "src/**/*.py", "app/services/*.py"]
    }
  ],
  "edges": [
    {
      "source": "source_node_id",
      "target": "target_node_id",
      "type": "depends_on|triggers|refutes|overrides|configures|secures"
    }
  ]
}
The "tags" field is optional but encouraged — use short lowercase labels like ["db", "migration", "breaking-change", "api", "auth", "llm"] to enable filtering. Omit if no clear category applies.
The "globs" field is an optional list of glob strings for Cursor rule matching. If the rule specifically applies to certain file paths or extensions (e.g., frontend code, backend services), generate the appropriate glob patterns. Omit if it's a global project rule.
Do not write markdown wraps like ```json or any other text before/after. Just the JSON object.
"""

CRITIC_PROMPT = """You are a Memory OS Knowledge Critic.
You review proposed memory nodes submitted by another LLM.
Your job is to be a skeptic — look for reasons to reject each node.

For each node ask:
1. Is this rule/fact durable and architectural, or just a one-time fix?
2. Is the summary specific and actionable, or generic boilerplate?
3. Is the evidence plausible for this type of node?

Return ONLY a raw JSON array, one entry per node:
[
  {"node_id": "example.node.id", "verdict": "approve", "reason": "Specific, durable architectural rule backed by concrete evidence."},
  {"node_id": "other.node.id", "verdict": "reject", "reason": "Too generic — applies to any Python project, not this codebase."}
]
No markdown, no wrapping text. Just the JSON array.
"""

COMPRESSION_PROMPT = """You are the Memory OS Graph Compressor.
Your job is to read all currently verified knowledge nodes, identify semantic duplicates or overlapping rules, and propose new unified nodes that merge them.
When you propose a new merged node, you MUST also output an "overrides" edge from the NEW node to ALL the OLD nodes it replaces, so the lifecycle manager knows to deprecate them.

Guidelines:
1. ONLY merge nodes if they conceptually overlap or represent the same underlying rule/fact.
2. If a node is standalone and fine as is, leave it alone (do not output it).
3. Output format is identical to standard compaction:
{
  "nodes": [
    {
      "id": "new.unified.node.id",
      "type": "rule",
      "summary": "Unified summary of the combined rules.",
      "evidence": ["path1.py", "path2.py"],
      "tags": ["merged", "optional-labels"]
    }
  ],
  "edges": [
    {
      "source": "new.unified.node.id",
      "target": "old.superseded.node.id",
      "type": "overrides"
    }
  ]
}
The "tags" field is optional — carry over merged source node tags, deduplicated. Omit if no clear category.
Do not write markdown wraps like ```json or any other text before/after. Just the JSON object.
"""

class MemoryCompactor:
    """Compacts task capsules into permanent Memory OS nodes using LLMs."""

    def __init__(
        self,
        config: Optional[IMemoryOSConfig] = None,
        repository: Optional[MemoryRepository] = None,
        llm_service: Optional[ILlmProviderService] = None,
    
    ):
        self.config = config or MemoryOSConfig()
        self.storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(self.storage, self.config)
        self.llm_service = llm_service or DefaultLlmProviderService()


    def _load_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        return self.storage.load_jsonl(path)

    def _append_jsonl(self, path: Path, item: Dict[str, Any]) -> None:
        self.storage.append_jsonl(path, item)

    def _clean_llm_json(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl:].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        return text

    def _call_llm(self, user_message: str, provider_override: Optional[str] = None, model_override: Optional[str] = None) -> str:
        return self.llm_service.call_llm(user_message, SYSTEM_PROMPT, provider_override, model_override)

    # ------------------------------------------------------------------
    # 3-critic panel
    # ------------------------------------------------------------------

    def _run_critic(self, critic_idx: int, nodes: List[Dict[str, Any]], provider: Optional[str], model: Optional[str]) -> List[Dict[str, Any]]:
        """Run one skeptic critic on proposed nodes. Returns list of {node_id, verdict, reason}."""
        slim = [{"node_id": n["id"], "type": n.get("type"), "summary": n.get("summary"), "evidence": n.get("evidence", [])} for n in nodes]
        user_msg = json.dumps({"nodes_to_review": slim}, ensure_ascii=False)
        try:
            raw = self.llm_service.call_llm(user_msg, CRITIC_PROMPT, provider, model)
            verdicts = json.loads(self._clean_llm_json(raw))
            if isinstance(verdicts, dict):
                verdicts = [verdicts]
            return [v for v in verdicts if isinstance(v, dict) and "node_id" in v and "verdict" in v]
        except Exception as exc:
            logger.warning(f"Critic {critic_idx} failed: {exc}")
            return [{"node_id": n["id"], "verdict": "reject", "reason": f"critic error: {exc}"} for n in nodes]

    def _panel_vote(self, proposed_nodes: List[Dict[str, Any]], provider: Optional[str], model: Optional[str]) -> tuple:
        """Run 3 independent critics in parallel. Node survives with >=2 approvals."""
        if not proposed_nodes:
            return [], []
        approval: Dict[str, int] = {n["id"]: 0 for n in proposed_nodes}
        all_votes: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self._run_critic, i, proposed_nodes, provider, model) for i in range(3)]
            for critic_idx, f in enumerate(futures):
                for vote in f.result():
                    nid = vote.get("node_id", "")
                    vote["critic_index"] = critic_idx
                    all_votes.append(vote)
                    if nid in approval and vote.get("verdict") == "approve":
                        approval[nid] += 1
        surviving = [n for n in proposed_nodes if approval.get(n["id"], 0) >= 2]
        rejected_ids = {n["id"] for n in proposed_nodes} - {n["id"] for n in surviving}
        if rejected_ids:
            logger.info(f"CriticPanel: {len(surviving)} survived, {len(rejected_ids)} rejected by majority: {rejected_ids}")
        return surviving, all_votes

    def _record_planned_deprecations(self, validator_name: str) -> None:
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        edges_path = self.config.memory_dir / "edges.jsonl"
        events_path = self.config.memory_dir / "events.jsonl"

        if not self.storage.exists(nodes_path) or not self.storage.exists(edges_path):
            return

        nodes = self._load_jsonl(nodes_path)
        edges = self._load_jsonl(edges_path)

        pre_verified_ids = {n["id"] for n in nodes if n.get("status") == "verified"}

        from memory_os.modules.lifecycle import LifecycleManager
        lifecycle = LifecycleManager(self.config)

        verified_ids = set()
        for node in nodes:
            if node.get("status") in ["draft", "observed"]:
                if (node.get("id") and node.get("summary") and
                    node.get("type") in ["rule", "fact", "variable", "connector", "config", "policy", "module_cluster"] and
                    lifecycle._validate_evidence(node.get("evidence", []))):
                    verified_ids.add(node["id"])

        all_verified_ids = pre_verified_ids | verified_ids

        for edge in edges:
            if edge.get("type") in ["overrides", "refutes"]:
                source_id = edge.get("source")
                target_id = edge.get("target")

                if source_id in all_verified_ids:
                    for n in nodes:
                        if n.get("id") == target_id and n.get("status") not in ["stale", "superseded"]:
                            new_status = "superseded" if edge["type"] == "overrides" else "stale"
                            dep_event = {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "event": "memory.node.deprecation_planned",
                                "node_id": target_id,
                                "claim": f"Planned deprecation to {new_status} via edge {edge['type']} from {source_id} (recorded by compactor)",
                                "evidence": n.get("evidence", []),
                                "validator": validator_name,
                                "status": "accepted"
                            }
                            self._append_jsonl(events_path, dep_event)
                            logger.info(f"Audit log: Node '{target_id}' is planned for deprecation to '{new_status}' due to edge '{edge['type']}' from '{source_id}'.")

    def _process_single_batch(self, args: tuple) -> Dict[str, Any]:
        """LLM call + 3-critic vote for one batch. No file I/O — returns pure data."""
        batch, batch_num, total_batches, existing_node_info, provider, model = args
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} capsules)...")

        user_msg_data = {
            "existing_nodes": existing_node_info,
            "new_tasks": [
                {
                    "timestamp": cap.get("timestamp"),
                    "task": cap.get("task"),
                    "workflow": cap.get("workflow"),
                    "files_modified": cap.get("files_modified", []),
                    "hurdles_regression": cap.get("hurdles_regression"),
                    "resolution": cap.get("resolution"),
                    "lessons_learned": cap.get("lessons_learned"),
                }
                for cap in batch
            ],
        }
        user_message = json.dumps(user_msg_data, indent=2, ensure_ascii=False)

        try:
            response_text = self._call_llm(user_message, provider, model)
        except Exception as exc:
            return {"batch_num": batch_num, "error": str(exc), "proposed_nodes": [], "proposed_edges": [], "timestamps": [], "critic_votes": []}

        json_text = self._clean_llm_json(response_text)
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            return {"batch_num": batch_num, "error": f"Invalid JSON: {exc}", "proposed_nodes": [], "proposed_edges": [], "timestamps": [], "critic_votes": []}

        try:
            proposed_nodes: List[Dict[str, Any]] = []
            proposed_edges: List[Dict[str, Any]] = []

            if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict) and ("nodes" in payload[0] or "edges" in payload[0]):
                payload = payload[0]

            if isinstance(payload, dict):
                proposed_nodes = payload.get("nodes", [])
                proposed_edges = payload.get("edges", [])
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        if "source" in item and "target" in item:
                            proposed_edges.append(item)
                        else:
                            proposed_nodes.append(item)

            # An LLM-returned shape can pass JSON parsing but still have the
            # wrong inner shape (e.g. {"nodes": ["bad"], ...} — strings, not
            # dicts). _panel_vote() assumes each node is a dict; without this
            # filter one malformed batch raises out of execute_parallel and
            # (per its own fix in scheduler.py) would otherwise drop every
            # other already-completed batch's results too.
            proposed_nodes = [n for n in proposed_nodes if isinstance(n, dict)]
            proposed_edges = [e for e in proposed_edges if isinstance(e, dict)]

            # 3-critic panel — runs 3 parallel LLM critics, requires 2/3 approval
            surviving_nodes, critic_votes = self._panel_vote(proposed_nodes, provider, model)

            return {
                "batch_num": batch_num,
                "error": None,
                "proposed_nodes": surviving_nodes,
                "proposed_edges": proposed_edges,
                "timestamps": [cap.get("timestamp") for cap in batch],
                "critic_votes": critic_votes,
            }
        except Exception as exc:
            return {"batch_num": batch_num, "error": f"batch processing failed: {exc}", "proposed_nodes": [], "proposed_edges": [], "timestamps": [], "critic_votes": []}

    def compact_capsules(self, provider: Optional[str] = None, model: Optional[str] = None) -> int:
        task_capsules_path = self.config.capsules_file
        events_path = self.config.memory_dir / "events.jsonl"
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        edges_path = self.config.memory_dir / "edges.jsonl"

        if not self.storage.exists(task_capsules_path):
            logger.error(f"Error: task_capsules.jsonl not found at {task_capsules_path}")
            return 1

        # 1. Load all task capsules
        capsules = [c.to_dict() for c in self.repository.get_task_capsules()]

        # 2. Get compacted timestamps from events
        compacted_timestamps: Set[str] = set()
        for ev in self._load_jsonl(events_path):
            if ev.get("event") == "memory.task_capsules.compacted":
                for ts in ev.get("compacted_timestamps", []):
                    compacted_timestamps.add(ts)

        # 3. Identify uncompacted capsules
        uncompacted = [cap for cap in capsules if cap.get("timestamp") not in compacted_timestamps]

        if not uncompacted:
            logger.info("No uncompacted capsules found.")
            try:
                self.archive_compacted_capsules()
            except Exception as exc:
                logger.error(f"Warning: capsule archiving failed: {exc}")
            return 0

        logger.info(f"Found {len(uncompacted)} uncompacted task capsules. Proceeding with compaction...")

        mode = getattr(self.config, "resource_mode", "normal")
        batch_size = 2 if mode == "quiet" else (10 if mode == "max" else 5)

        # Read existing nodes ONCE — snapshot shared across all parallel batches (read-only)
        existing_nodes = [n.to_dict() for n in self.repository.get_nodes()]
        existing_node_info = [{"id": n["id"], "type": n["type"], "summary": n["summary"]} for n in existing_nodes]
        existing_node_ids: Set[str] = {n["id"] for n in existing_nodes}

        batches = [uncompacted[i:i + batch_size] for i in range(0, len(uncompacted), batch_size)]
        total_batches = len(batches)
        batch_args = [(batch, idx + 1, total_batches, existing_node_info, provider, model) for idx, batch in enumerate(batches)]

        # --- Parallel: LLM calls + 3-critic votes across all batches ---
        scheduler = HardwareScheduler(mode=mode)
        results: List[Dict[str, Any]] = scheduler.execute_parallel(self._process_single_batch, batch_args)
        results.sort(key=lambda r: r.get("batch_num", -1))

        # --- Sequential: EvolutionGate (needs incremental dedup state) ---
        existing_edges = self._load_jsonl(edges_path)
        existing_verified = [n for n in existing_nodes if n.get("status") == "verified"]
        gate = EvolutionGate(
            existing_node_ids=existing_node_ids,
            existing_edges=existing_edges,
            existing_verified_nodes=existing_verified,
        )

        try:
            rel_capsules = str(self.config.capsules_file.relative_to(self.config.root_dir))
        except ValueError:
            rel_capsules = "agent_context/task_capsules.jsonl"

        # Buffer all writes — worktree isolation: no file I/O until all batches are processed
        nodes_buffer: List[Dict[str, Any]] = []
        edges_buffer: List[Dict[str, Any]] = []
        events_buffer: List[Dict[str, Any]] = []
        new_node_ids: Set[str] = set()

        for result in results:
            batch_num = result.get("batch_num", "?")

            if result.get("error"):
                logger.error(f"Batch {batch_num} failed: {result['error']} — skipping")
                continue

            gate_report = gate.check_nodes(result["proposed_nodes"])
            for line in gate_report.summary_lines():
                logger.info(line)

            for verdict in gate_report.rejected:
                events_buffer.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.node.rejected",
                    "node_id": verdict.node.get("id", "unknown"),
                    "claim": f"Rejected at stage '{verdict.stage}': {verdict.reason}",
                    "evidence": verdict.node.get("evidence", []),
                    "validator": "evolution_gate",
                    "status": "rejected",
                    "stage": verdict.stage,
                    "reason": verdict.reason,
                })

            for node in gate_report.accepted:
                node_id = node.get("id")
                node_type = node.get("type")
                summary = node.get("summary")
                evidence = node.get("evidence", [])

                cleaned_evidence = [fp for fp in evidence if (self.config.root_dir / fp).exists()]
                seen: Set[str] = set()
                cleaned_evidence = [fp for fp in cleaned_evidence if not (fp in seen or seen.add(fp))]
                if rel_capsules not in cleaned_evidence:
                    cleaned_evidence.append(rel_capsules)

                new_node = {
                    "id": node_id,
                    "type": node_type,
                    "summary": summary,
                    "evidence": cleaned_evidence,
                    "status": "draft",
                    "freshness": datetime.now().isoformat(timespec="seconds"),
                    "trust": "unverified",
                    "related_nodes": [],
                    "tags": node.get("tags", []),
                }
                nodes_buffer.append(new_node)
                new_node_ids.add(node_id)
                existing_node_ids.add(node_id)
                existing_node_info.append({"id": node_id, "type": node_type, "summary": summary})
                logger.info(f"Accepted node '{node_id}' (draft).")

                events_buffer.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.node.proposed",
                    "node_id": node_id,
                    "claim": f"Propose rule/fact: {summary}",
                    "evidence": cleaned_evidence,
                    "validator": "evolution_gate",
                    "status": "pending",
                })

            all_ids = existing_node_ids | new_node_ids
            accepted_batch_node_ids = {node.get("id") for node in gate_report.accepted}
            for edge in result["proposed_edges"]:
                source, target, edge_type = edge.get("source"), edge.get("target"), edge.get("type")
                if not source or not target or not edge_type:
                    continue
                if edge_type not in VALID_EDGE_TYPES:
                    continue
                if source not in all_ids or target not in all_ids:
                    continue

                if edge_type in ["overrides", "refutes"]:
                    if source not in accepted_batch_node_ids:
                        logger.warning(f"Rejecting edge {source} --{edge_type}--> {target} because source was not accepted in this batch.")
                        events_buffer.append({
                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                            "event": "memory.edge.rejected",
                            "node_id": source,
                            "claim": f"Rejected edge: {source} -> {target} ({edge_type}) because source node was not accepted in this batch.",
                            "evidence": [],
                            "validator": "evolution_gate",
                            "status": "rejected",
                            "reason": "destructive edge source not accepted in same batch",
                        })
                        continue

                edges_buffer.append({"source": source, "target": target, "type": edge_type})

            # Log critic votes
            for vote in result.get("critic_votes", []):
                events_buffer.append({
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.critic.vote",
                    "node_id": vote.get("node_id", "unknown"),
                    "claim": vote.get("reason", ""),
                    "evidence": [],
                    "validator": f"critic_{vote.get('critic_index', '?')}",
                    "status": "accepted" if vote.get("verdict") == "approve" else "rejected",
                })

            events_buffer.append({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "memory.task_capsules.compacted",
                "node_id": "memory.task_capsules.compactor",
                "claim": f"Compacted batch {batch_num}/{total_batches} ({len(result['timestamps'])} capsules).",
                "evidence": [rel_capsules],
                "validator": "memory_os_compactor",
                "status": "accepted",
                "compacted_timestamps": result["timestamps"],
            })

        # --- Atomic write: flush all buffers to disk ---
        for node in nodes_buffer:
            self._append_jsonl(nodes_path, node)
            exporter = PolyglotExporter(self.config.root_dir)
            exporter.export_node(node["id"], node["type"], node["summary"], node["evidence"], None)
        for edge in edges_buffer:
            self._append_jsonl(edges_path, edge)
            logger.info(f"Appended edge: {edge['source']} -> {edge['target']} ({edge['type']})")
        for event in events_buffer:
            self._append_jsonl(events_path, event)

        logger.info(f"Compaction completed. Proposed {len(nodes_buffer)} nodes, appended {len(edges_buffer)} edges.")

        # Record planned deprecations before calling lifecycle
        self._record_planned_deprecations(validator_name="memory_os_compactor")

        # Trigger lifecycle transitions and manifest compilation via classes
        from memory_os.modules.lifecycle import LifecycleManager

        logger.info("Running lifecycle transition validations...")
        lifecycle = LifecycleManager(self.config)
        lifecycle.transition(validator="memory_os_compactor")
        lifecycle.prune()
        lifecycle.manifest()

        # Archive compacted capsules to prevent context bloat
        try:
            self.archive_compacted_capsules()
        except Exception as exc:
            logger.error(f"Warning: capsule archiving failed: {exc}")

        # Rebuild snapshot
        logger.info("Updating memory snapshot...")
        try:
            from memory_os.modules.context import ContextRegistry
            registry = ContextRegistry(str(self.config.root_dir))
            snapshot = registry.build_snapshot(paths=["."])
            snapshot_file = self.config.snapshot_file
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            with open(snapshot_file, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
            logger.info(f"Snapshot successfully written to {snapshot_file}")
        except Exception as exc:
            logger.error(f"Warning: snapshot rebuild failed: {exc}")

        return 0

    def compress_graph(self, provider: Optional[str] = None, model: Optional[str] = None, dry_run: bool = False) -> int:
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        edges_path = self.config.memory_dir / "edges.jsonl"
        events_path = self.config.memory_dir / "events.jsonl"

        if not self.storage.exists(nodes_path):
            logger.error(f"Error: nodes.jsonl not found at {nodes_path}")
            return 1

        nodes = [n.to_dict() for n in self.repository.get_nodes()]
        verified_nodes = [n for n in nodes if n["status"] == "verified"]

        if len(verified_nodes) < 2:
            logger.info("Not enough verified nodes to compress.")
            return 0

        logger.info(f"Analyzing {len(verified_nodes)} verified nodes for compression...")

        user_msg_data = {
            "verified_nodes": [{"id": n["id"], "type": n["type"], "summary": n["summary"]} for n in verified_nodes]
        }
        user_message = json.dumps(user_msg_data, indent=2, ensure_ascii=False)

        try:
            response_text = self.llm_service.call_llm(user_message, COMPRESSION_PROMPT, provider, model)
        except Exception as exc:
            logger.error(f"Error during LLM compression call: {exc}")
            return 1

        json_text = self._clean_llm_json(response_text)
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            logger.error(f"Error: LLM returned invalid JSON for compression: {exc}\nRaw Response:\n{response_text}")
            return 1

        proposed_nodes = []
        proposed_edges = []

        if isinstance(payload, dict):
            proposed_nodes = payload.get("nodes", [])
            proposed_edges = payload.get("edges", [])

        if not proposed_nodes and not proposed_edges:
            logger.info("LLM did not propose any compressions. Graph is already optimal.")
            return 0

        # 3-critic panel — same quality bar as compact_capsules
        surviving_nodes, critic_votes = self._panel_vote(proposed_nodes, provider, model)
        if proposed_nodes and not surviving_nodes:
            logger.info("CriticPanel: all compression proposals rejected. Graph is already optimal.")
            return 0
        proposed_nodes = surviving_nodes

        if dry_run:
            logger.info(f"[dry-run] Would merge {len(proposed_nodes)} node(s):")
            for n in proposed_nodes:
                logger.info(f"  + {n.get('id')}  ({n.get('type')})  {n.get('summary', '')[:80]}")
            logger.info(f"[dry-run] Would append {len(proposed_edges)} override edge(s):")
            for e in proposed_edges:
                logger.info(f"  {e.get('source')} --{e.get('type')}--> {e.get('target')}")
            return 0

        existing_edges = self._load_jsonl(edges_path)
        existing_node_ids = {n["id"] for n in nodes}
        gate = EvolutionGate(
            existing_node_ids=existing_node_ids,
            existing_edges=existing_edges,
            existing_verified_nodes=verified_nodes,
        )
        gate_report = gate.check_nodes(proposed_nodes)

        for line in gate_report.summary_lines():
            logger.info(line)

        # Pre-compute existing edge set for dedup
        existing_edge_keys: Set[tuple] = {
            (e.get("source"), e.get("target"), e.get("type")) for e in existing_edges
        }

        try:
            rel_capsules = str(self.config.capsules_file.relative_to(self.config.root_dir))
        except ValueError:
            rel_capsules = "agent_context/task_capsules.jsonl"

        for verdict in gate_report.rejected:
            rejected_id = verdict.node.get("id", "unknown")
            self._append_jsonl(events_path, {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "memory.node.rejected",
                "node_id": rejected_id,
                "claim": f"Rejected at stage '{verdict.stage}': {verdict.reason}",
                "evidence": verdict.node.get("evidence", []),
                "validator": "evolution_gate",
                "status": "rejected",
                "stage": verdict.stage,
                "reason": verdict.reason,
            })

        # Log critic votes to events
        for vote in critic_votes:
            self._append_jsonl(events_path, {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "memory.critic.vote",
                "node_id": vote.get("node_id", "unknown"),
                "claim": vote.get("reason", ""),
                "evidence": [],
                "validator": f"critic_{vote.get('critic_index', '?')}",
                "status": "accepted" if vote.get("verdict") == "approve" else "rejected",
            })

        new_node_ids: Set[str] = set()
        node_append_count = 0
        edge_append_count = 0

        for node in gate_report.accepted:
            node_id = node.get("id")

            # Clean evidence: keep only paths that exist on disk
            evidence = node.get("evidence", [])
            cleaned_evidence = [fp for fp in evidence if (self.config.root_dir / fp).exists()]
            seen: Set[str] = set()
            cleaned_evidence = [fp for fp in cleaned_evidence if not (fp in seen or seen.add(fp))]
            if not cleaned_evidence:
                cleaned_evidence = [rel_capsules]

            new_node = {
                "id": node_id,
                "type": node.get("type", "rule"),
                "summary": node.get("summary", ""),
                "evidence": cleaned_evidence,
                "status": "draft",
                "freshness": datetime.now().isoformat(timespec="seconds"),
                "trust": "unverified",
                "related_nodes": [],
                "tags": node.get("tags", []),
            }
            self._append_jsonl(nodes_path, new_node)
            new_node_ids.add(node_id)
            node_append_count += 1
            logger.info(f"Proposed compressed node '{node_id}' added as draft.")

            exporter = PolyglotExporter(self.config.root_dir)
            exporter.export_node(node_id, new_node["type"], new_node["summary"], new_node["evidence"], node.get("globs"))

            self._append_jsonl(events_path, {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "memory.node.proposed",
                "node_id": node_id,
                "claim": f"Compressed rule: {new_node['summary']}",
                "evidence": new_node["evidence"],
                "validator": "evolution_gate",
                "status": "pending",
            })

        for edge in proposed_edges:
            source = edge.get("source")
            target = edge.get("target")
            edge_type = edge.get("type")

            if edge_type != "overrides":
                logger.warning(f"Rejecting edge {source} --{edge_type}--> {target} because type is not 'overrides' in compress_graph.")
                self._append_jsonl(events_path, {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.edge.rejected",
                    "node_id": source or "unknown",
                    "claim": f"Rejected edge: {source} -> {target} ({edge_type}) because type is not 'overrides' for compression.",
                    "evidence": [],
                    "validator": "evolution_gate",
                    "status": "rejected",
                    "reason": "edge type is not 'overrides' for compression",
                })
                continue

            if edge_type not in VALID_EDGE_TYPES:
                logger.warning(f"Rejecting edge {source} --{edge_type}--> {target} because type is not in VALID_EDGE_TYPES.")
                self._append_jsonl(events_path, {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.edge.rejected",
                    "node_id": source or "unknown",
                    "claim": f"Rejected edge: {source} -> {target} ({edge_type}) because type is not a valid edge type.",
                    "evidence": [],
                    "validator": "evolution_gate",
                    "status": "rejected",
                    "reason": "invalid edge type",
                })
                continue

            if source not in new_node_ids:
                logger.warning(f"Rejecting edge {source} --{edge_type}--> {target} because source was not accepted in this compression run.")
                self._append_jsonl(events_path, {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.edge.rejected",
                    "node_id": source,
                    "claim": f"Rejected edge: {source} -> {target} ({edge_type}) because source node was not accepted in this compression run.",
                    "evidence": [],
                    "validator": "evolution_gate",
                    "status": "rejected",
                    "reason": "compression edge source not in new_node_ids",
                })
                continue

            if target not in existing_node_ids:
                logger.warning(f"Rejecting edge {source} --{edge_type}--> {target} because target is not in existing_node_ids.")
                self._append_jsonl(events_path, {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.edge.rejected",
                    "node_id": source,
                    "claim": f"Rejected edge: {source} -> {target} ({edge_type}) because target is not in existing_node_ids.",
                    "evidence": [],
                    "validator": "evolution_gate",
                    "status": "rejected",
                    "reason": "compression edge target not in existing_node_ids",
                })
                continue

            key = (source, target, edge_type)
            if key in existing_edge_keys:
                logger.info(f"Skipping duplicate edge: {key[0]} --{key[2]}--> {key[1]}")
                continue

            self._append_jsonl(edges_path, edge)
            existing_edge_keys.add(key)
            edge_append_count += 1
            logger.info(f"Appended compression edge: {source} -> {target} ({edge_type})")

        logger.info(f"Compression completed. Proposed {node_append_count} merged nodes, appended {edge_append_count} override edges.")

        if node_append_count > 0:
            # Record planned deprecations before calling lifecycle
            self._record_planned_deprecations(validator_name="memory_os_compressor")

            from memory_os.modules.lifecycle import LifecycleManager
            logger.info("Running lifecycle transition validations to deprecate old nodes...")
            lifecycle = LifecycleManager(self.config)
            lifecycle.transition(validator="memory_os_compressor")
            lifecycle.prune()
            lifecycle.manifest()

            logger.info("Updating memory snapshot...")
            try:
                from memory_os.modules.context import ContextRegistry
                registry = ContextRegistry(str(self.config.root_dir))
                snapshot = registry.build_snapshot(paths=["."])
                snapshot_file = self.config.snapshot_file
                snapshot_file.parent.mkdir(parents=True, exist_ok=True)
                with open(snapshot_file, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2, ensure_ascii=False)
                logger.info(f"Snapshot successfully written to {snapshot_file}")
            except Exception as exc:
                logger.error(f"Warning: snapshot rebuild failed: {exc}")

        return 0

    def archive_compacted_capsules(self, keep_recent: int = 5) -> None:
        task_capsules_path = self.config.capsules_file
        if not self.storage.exists(task_capsules_path):
            return

        archive_path = task_capsules_path.parent / "archived_task_capsules.jsonl"

        # 1. Load all task capsules
        capsules = [c.to_dict() for c in self.repository.get_task_capsules()]

        # 2. Get compacted timestamps from events
        events_path = self.config.memory_dir / "events.jsonl"
        compacted_timestamps = set()
        if self.storage.exists(events_path):
            events = self._load_jsonl(events_path)
            for ev in events:
                if ev.get("event") == "memory.task_capsules.compacted":
                    timestamps = ev.get("compacted_timestamps", [])
                    for ts in timestamps:
                        compacted_timestamps.add(ts)

        # 3. Separate compacted vs uncompacted
        compacted = []
        uncompacted = []
        for cap in capsules:
            ts = cap.get("timestamp")
            if ts in compacted_timestamps:
                compacted.append(cap)
            else:
                uncompacted.append(cap)

        if not compacted:
            return

        # 4. Read existing archived timestamps to avoid duplicates
        archived_timestamps = set()
        if self.storage.exists(archive_path):
            archived = self._load_jsonl(archive_path)
            for cap in archived:
                ts = cap.get("timestamp")
                if ts:
                    archived_timestamps.add(ts)

        # 5. Append newly compacted ones to archived_task_capsules.jsonl
        archive_append_count = 0
        for cap in compacted:
            ts = cap.get("timestamp")
            if ts not in archived_timestamps:
                self.storage.append_jsonl(archive_path, cap)
                archive_append_count += 1

        if archive_append_count > 0:
            logger.info(f"INFO: Archived {archive_append_count} compacted capsules to {archive_path.name}")

        # 6. Keep all uncompacted + last `keep_recent` compacted in task_capsules.jsonl
        retained_compacted = compacted[-keep_recent:] if len(compacted) > keep_recent else compacted

        def get_ts(c):
            return c.get("timestamp", "")

        final_capsules = sorted(uncompacted + retained_compacted, key=get_ts)

        self.storage.save_jsonl(task_capsules_path, final_capsules)
