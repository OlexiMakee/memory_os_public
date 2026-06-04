from memory_os.core.logger import get_logger
logger = get_logger(__name__)
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Any, Optional

from memory_os.core.interfaces import IMemoryOSConfig, IMemoryStorage, ILlmProviderService
from memory_os.core.repository import MemoryRepository
from memory_os.core.models import MemoryNode, MemoryEdge, NodeType, EdgeType
from memory_os.core.exceptions import MemoryOSError, ValidationError
from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.llm_service import DefaultLlmProviderService

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
      "evidence": ["relative/file/path.py"]
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
Do not write markdown wraps like ```json or any other text before/after. Just the JSON object.
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
      "evidence": ["path1.py", "path2.py"]
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
        storage = FileSystemMemoryStorage()
        self.repository = repository or MemoryRepository(storage, self.config)
        self.llm_service = llm_service or DefaultLlmProviderService()


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
        compacted_timestamps = set()
        events = self._load_jsonl(events_path)
        for ev in events:
            if ev.get("event") == "memory.task_capsules.compacted":
                timestamps = ev.get("compacted_timestamps", [])
                for ts in timestamps:
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

        # Determine batch size based on resource mode
        mode = getattr(self.config, "resource_mode", "normal")
        if mode == "quiet":
            batch_size = 2
        elif mode == "max":
            batch_size = 10
        else:
            batch_size = 5
            
        total_batches = (len(uncompacted) + batch_size - 1) // batch_size
        node_append_count = 0
        edge_append_count = 0

        for i in range(0, len(uncompacted), batch_size):
            batch = uncompacted[i:i+batch_size]
            batch_num = (i // batch_size) + 1
            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} capsules)...")

            # Read existing nodes for reference
            existing_nodes = [n.to_dict() for n in self.repository.get_nodes()]
            existing_node_info = [{"id": n["id"], "type": n["type"], "summary": n["summary"]} for n in existing_nodes]

            # Build user message for this batch
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
                        "lessons_learned": cap.get("lessons_learned")
                    }
                    for cap in batch
                ]
            }

            user_message = json.dumps(user_msg_data, indent=2, ensure_ascii=False)

            # Call LLM
            try:
                response_text = self._call_llm(user_message, provider, model)
            except Exception as exc:
                raise MemoryOSError(f"Error during LLM call in batch {batch_num}: {exc}")

            # Parse and clean output
            json_text = self._clean_llm_json(response_text)
            try:
                payload = json.loads(json_text)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Error: LLM returned invalid JSON in batch {batch_num}: {exc}")

            proposed_nodes = []
            proposed_edges = []

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

            existing_node_ids = {n["id"] for n in existing_nodes}
            new_node_ids = set()

            valid_node_types = {t.value for t in NodeType}

            for node in proposed_nodes:
                node_id = node.get("id")
                node_type = node.get("type")
                summary = node.get("summary")
                evidence = node.get("evidence", [])

                if not node_id or not node_type or not summary:
                    logger.info(f"Skipping invalid proposed node: {node}")
                    continue

                if node_type not in valid_node_types:
                    logger.info(f"Skipping proposed node '{node_id}' with invalid type '{node_type}'")
                    continue

                if node_id in existing_node_ids:
                    logger.info(f"Node '{node_id}' already exists in nodes.jsonl. Skipping proposal.")
                    continue

                # Clean evidence: keep only existing files, and always add the capsules file
                cleaned_evidence = []
                for file_path in evidence:
                    if (self.config.root_dir / file_path).exists() and file_path not in cleaned_evidence:
                        cleaned_evidence.append(file_path)
                
                # Check capsules relative path to root_dir
                try:
                    rel_capsules = str(self.config.capsules_file.relative_to(self.config.root_dir))
                except ValueError:
                    rel_capsules = "agent_context/task_capsules.jsonl"
                
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
                    "related_nodes": []
                }

                self._append_jsonl(nodes_path, new_node)
                new_node_ids.add(node_id)
                node_append_count += 1
                logger.info(f"Proposed node '{node_id}' added as draft.")

                # Log node proposed event
                new_event = {
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                    "event": "memory.node.proposed",
                    "node_id": node_id,
                    "claim": f"Propose rule/fact: {summary}",
                    "evidence": cleaned_evidence,
                    "validator": "memory_os_compactor",
                    "status": "pending"
                }
                self._append_jsonl(events_path, new_event)

            # Validate and append edges
            valid_edge_types = {"depends_on", "triggers", "refutes", "overrides", "configures", "secures"}

            for edge in proposed_edges:
                source = edge.get("source")
                target = edge.get("target")
                edge_type = edge.get("type")

                if not source or not target or not edge_type:
                    logger.info(f"Skipping invalid proposed edge: {edge}")
                    continue

                if edge_type not in valid_edge_types:
                    logger.info(f"Skipping proposed edge source='{source}' target='{target}' with invalid type '{edge_type}'")
                    continue

                # Source/target must exist either in existing nodes or new proposed nodes
                all_ids = existing_node_ids.union(new_node_ids)
                if source not in all_ids or target not in all_ids:
                    logger.info(f"Skipping edge {source} -> {target} because source or target node is missing.")
                    continue

                new_edge = {
                    "source": source,
                    "target": target,
                    "type": edge_type
                }
                self._append_jsonl(edges_path, new_edge)
                edge_append_count += 1
                logger.info(f"Appended edge: {source} -> {target} ({edge_type})")

            # Log compaction completion event for this batch
            batch_timestamps = [cap.get("timestamp") for cap in batch]
            
            try:
                rel_capsules = str(self.config.capsules_file.relative_to(self.config.root_dir))
            except ValueError:
                rel_capsules = "agent_context/task_capsules.jsonl"
                
            compaction_event = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "memory.task_capsules.compacted",
                "node_id": "memory.task_capsules.compactor",
                "claim": f"Compacted batch {batch_num}/{total_batches} ({len(batch)} capsules).",
                "evidence": [rel_capsules],
                "validator": "memory_os_compactor",
                "status": "accepted",
                "compacted_timestamps": batch_timestamps
            }
            self._append_jsonl(events_path, compaction_event)
            
            # Resource politeness pause
            if mode == "quiet" and i + batch_size < len(uncompacted):
                import time
                logger.info("Quiet mode: resting for 5 seconds between batches...")
                time.sleep(5)

        logger.info(f"Compaction completed. Proposed {node_append_count} nodes, appended {edge_append_count} edges.")

        # Trigger lifecycle transitions and manifest compilation via classes
        from memory_os.modules.lifecycle import LifecycleManager

        logger.info("Running lifecycle transition validations...")
        lifecycle = LifecycleManager(self.config, self.storage)
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
            import subprocess
            # Rebuild snapshot relative to config
            compact_memory_script = self.config.root_dir / "scripts" / "compact_memory.py"
            if self.storage.exists(compact_memory_script):
                subprocess.run([sys.executable, str(compact_memory_script), "--write"], check=True)
        except Exception as exc:
            logger.error(f"Warning: snapshot rebuild failed: {exc}")

        return 0

    def compress_graph(self, provider: Optional[str] = None, model: Optional[str] = None) -> int:
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

        existing_node_ids = {n["id"] for n in nodes}
        new_node_ids = set()

        node_append_count = 0
        edge_append_count = 0

        for node in proposed_nodes:
            node_id = node.get("id")
            if not node_id or node_id in existing_node_ids:
                continue
            
            new_node = {
                "id": node_id,
                "type": node.get("type", "rule"),
                "summary": node.get("summary", ""),
                "evidence": node.get("evidence", []),
                "status": "draft",
                "freshness": datetime.now().isoformat(timespec="seconds"),
                "trust": "unverified",
                "related_nodes": []
            }
            self._append_jsonl(nodes_path, new_node)
            new_node_ids.add(node_id)
            node_append_count += 1
            logger.info(f"Proposed compressed node '{node_id}' added as draft.")

            new_event = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "memory.node.proposed",
                "node_id": node_id,
                "claim": f"Compressed rule: {new_node['summary']}",
                "evidence": new_node["evidence"],
                "validator": "memory_os_compressor",
                "status": "pending"
            }
            self._append_jsonl(events_path, new_event)

        for edge in proposed_edges:
            if edge.get("source") in new_node_ids and edge.get("target") in existing_node_ids:
                self._append_jsonl(edges_path, edge)
                edge_append_count += 1
                logger.info(f"Appended compression edge: {edge['source']} -> {edge['target']} ({edge['type']})")

        logger.info(f"Compression completed. Proposed {node_append_count} merged nodes, appended {edge_append_count} override edges.")

        if node_append_count > 0:
            from memory_os.modules.lifecycle import LifecycleManager
            logger.info("Running lifecycle transition validations to deprecate old nodes...")
            lifecycle = LifecycleManager(self.config, self.storage)
            lifecycle.transition(validator="memory_os_compressor")
            lifecycle.prune()
            lifecycle.manifest()

            logger.info("Updating memory snapshot...")
            try:
                import subprocess
                compact_memory_script = self.config.root_dir / "scripts" / "compact_memory.py"
                if self.storage.exists(compact_memory_script):
                    subprocess.run([sys.executable, str(compact_memory_script), "--write"], check=True)
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
