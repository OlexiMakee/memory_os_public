import os
from pathlib import Path
from typing import Dict, Any, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage

# Files inside the project root that /api/read_file must never serve, even
# though they pass plain root-confinement (they live INSIDE the project, not
# outside it). Covers secrets (.env), VCS internals, and raw DB files.
_DENIED_PATH_PARTS = {".env", ".git", ".ssh"}
_DENIED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key"}
MAX_READABLE_FILE_BYTES = 10 * 1024 * 1024

class IGraphDataProvider:
    """
    Abstract interface representing the boundary between HTTP presentation
    and internal data structures. This is where we will hook up Rust/Go
    optimizations in the future when the graph scales.
    """
    def get_graph_data(self) -> Dict[str, Any]:
        raise NotImplementedError

    def read_evidence_file(self, file_path: str) -> Optional[bytes]:
        raise NotImplementedError


class DefaultGraphDataProvider(IGraphDataProvider):
    """
    Default Python-based data provider.
    Reads graph from SQLite/JSON and enforces local file security bounds.
    """
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        storage = FileSystemMemoryStorage()
        self.repo = MemoryRepository(storage, config)

    def get_graph_data(self) -> Dict[str, Any]:
        """
        Retrieves all nodes and edges from the memory repository
        and formats them for 3D Force Graph consumption.
        """
        nodes = self.repo.get_nodes()
        edges = self.repo.get_edges()
        
        # Format nodes and links
        formatted_nodes = []
        project_root = self.config.root_dir.resolve()
        
        for n in nodes:
            node_dict = {
                "id": n.id,
                "type": n.type,
                "summary": n.summary,
                "tags": n.tags,
                "status": getattr(n, 'status', 'observed'),
                "trust": getattr(n, 'trust', 'extracted'),
                "evidence": n.evidence,
                "freshness": getattr(n, 'freshness', '')
            }
            
            # Attach physical file properties if it's a file
            if n.type == 'file' and n.evidence:
                file_path = self._resolve_file_path(n.evidence[0], project_root)
                if file_path:
                    try:
                        node_dict["file_size"] = file_path.stat().st_size
                    except Exception:
                        pass

            formatted_nodes.append(node_dict)

        formatted_links = []
        for e in edges:
            link_dict = {
                "source": e.source,
                "target": e.target,
                "relation": e.type,
                "weight": getattr(e, 'weight', 1.0)
            }
            formatted_links.append(link_dict)

        return {
            "nodes": formatted_nodes,
            "links": formatted_links
        }

    @staticmethod
    def _is_denied_path(path: Path) -> bool:
        """True for files that must never be served, even if inside project_root."""
        for part in path.parts:
            if part == ".git" or part == ".ssh" or part.startswith(".env"):
                return True
        return path.suffix.lower() in _DENIED_SUFFIXES

    def _resolve_file_path(self, file_path_str: str, project_root: Path) -> Optional[Path]:
        """Resolves an evidence file path to an absolute Path, using fallback rglob if needed."""
        target_path = Path(file_path_str).resolve()
        try:
            target_path.relative_to(project_root)
        except ValueError:
            return None  # escapes project_root (string-prefix matching would
            # wrongly accept a sibling dir like "memory_os_secrets")

        if self._is_denied_path(target_path.relative_to(project_root)):
            return None

        if target_path.exists() and target_path.is_file():
            return target_path

        # Fallback: search for the filename in the project directory recursively
        found = list(project_root.rglob(target_path.name))
        found = [
            f for f in found
            if not any(part.startswith('.') or part == '__pycache__' or part == 'venv_auto' for part in f.parts)
            and not self._is_denied_path(f.relative_to(project_root))
        ]

        if not found:
            return None
        return found[0]

    def read_evidence_file(self, file_path: str) -> Optional[bytes]:
        """
        Safely reads a local file from disk.
        Returns bytes if successful, None if the file is outside boundaries,
        denied, too large, or unreadable.
        """
        try:
            project_root = self.config.root_dir.resolve()
            target_path = self._resolve_file_path(file_path, project_root)

            if not target_path:
                return None

            if target_path.stat().st_size > MAX_READABLE_FILE_BYTES:
                return None

            with open(target_path, "rb") as f:
                return f.read()
        except Exception:
            return None
