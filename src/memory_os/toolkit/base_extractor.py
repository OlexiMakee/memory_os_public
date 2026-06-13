import abc
import json
from datetime import datetime
from typing import List, Dict, Any, Tuple
from pathlib import Path

from memory_os import MemoryOSConfig
from memory_os.core.logger import get_logger
from memory_os.modules.validator import MemoryValidator

logger = get_logger(__name__)

class DataExtractor(abc.ABC):
    """Abstract base class for all data synchronization extractors."""
    
    @abc.abstractmethod
    def extract_capsules(self) -> List[Dict[str, Any]]:
        """Returns a list of TaskCapsule dictionaries."""
        pass
        
    @abc.abstractmethod
    def extract_nodes_and_edges(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Returns a tuple of (List[MemoryNode dicts], List[MemoryEdge dicts])."""
        pass


class DocumentIngestor:
    """Handles the persistence of extracted data into Memory OS storage."""
    
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        
    def ingest(self, extractor: DataExtractor, to_capsules: bool) -> bool:
        if to_capsules:
            return self._ingest_capsules(extractor)
        else:
            return self._ingest_graph(extractor)
            
    def _ingest_capsules(self, extractor: DataExtractor) -> bool:
        capsules_file = self.config.capsules_file
        existing_capsules = []
        if capsules_file.exists():
            with open(capsules_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing_capsules.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                        
        seen_tasks = {cap.get("task") for cap in existing_capsules}
        
        new_capsules = extractor.extract_capsules()
        added_count = 0
        for cap in new_capsules:
            if cap.get("task") not in seen_tasks:
                existing_capsules.append(cap)
                seen_tasks.add(cap.get("task"))
                added_count += 1
                
        capsules_file.parent.mkdir(parents=True, exist_ok=True)
        with open(capsules_file, "w", encoding="utf-8") as f:
            for cap in existing_capsules:
                f.write(json.dumps(cap, ensure_ascii=False) + "\n")
                
        logger.info(f"Task capsules sync complete. Appended {added_count} new task capsules.")
        return True

    def _ingest_graph(self, extractor: DataExtractor) -> bool:
        nodes_path = self.config.memory_dir / "nodes.jsonl"
        edges_path = self.config.memory_dir / "edges.jsonl"
        
        # Load existing nodes
        existing_nodes = {}
        if nodes_path.exists():
            with open(nodes_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        node_data = json.loads(line)
                        if "id" in node_data:
                            existing_nodes[node_data["id"]] = node_data
                    except json.JSONDecodeError:
                        continue
                        
        # Load existing edges
        existing_edges = []
        if edges_path.exists():
            with open(edges_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing_edges.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                        
        seen_edges = set()
        for edge in existing_edges:
            seen_edges.add((edge.get("source"), edge.get("target"), edge.get("type")))

        new_nodes, new_edges = extractor.extract_nodes_and_edges()
        
        # Merge nodes
        updated_count = 0
        created_count = 0
        for node in new_nodes:
            node_id = node["id"]
            if node_id in existing_nodes:
                existing_nodes[node_id].update(node)
                updated_count += 1
            else:
                existing_nodes[node_id] = node
                created_count += 1
                
        # Merge edges
        new_edges_added = 0
        for edge in new_edges:
            edge_key = (edge.get("source"), edge.get("target"), edge.get("type"))
            if edge_key not in seen_edges:
                existing_edges.append(edge)
                seen_edges.add(edge_key)
                new_edges_added += 1

        self.config.memory_dir.mkdir(parents=True, exist_ok=True)
        with open(nodes_path, "w", encoding="utf-8") as f:
            for node in existing_nodes.values():
                f.write(json.dumps(node, ensure_ascii=False) + "\n")
                
        with open(edges_path, "w", encoding="utf-8") as f:
            for edge in existing_edges:
                f.write(json.dumps(edge, ensure_ascii=False) + "\n")
                
        logger.info(f"Graph sync complete. Created {created_count} nodes, updated {updated_count} nodes, added {new_edges_added} edges.")
        
        # Validation and Indexing
        validator = MemoryValidator(self.config)
        errors = []
        errors.extend(validator.validate_nodes())
        errors.extend(validator.validate_edges())
        errors.extend(validator.validate_events())
        if errors:
            logger.warning("Validation warnings/errors after sync:\n" + "\n".join(errors))
            
        logger.info("Syncing memories to SQLite search index...")
        from memory_os.core.repository import MemoryRepository
        from memory_os.core.storage import FileSystemMemoryStorage
        repo = MemoryRepository(FileSystemMemoryStorage(), self.config)
        repo.sync_graph_nodes()
        logger.info("SQLite search index synced successfully.")
        
        return True
