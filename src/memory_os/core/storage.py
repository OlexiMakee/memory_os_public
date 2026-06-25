import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any
from memory_os.core.interfaces import IMemoryStorage

class FileSystemMemoryStorage(IMemoryStorage):
    """Concrete implementation of IMemoryStorage using the local filesystem."""

    def load_jsonl(self, filepath: Path) -> List[Dict[str, Any]]:
        if not filepath.exists():
            return []
        items = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return items

    def save_jsonl(self, filepath: Path, items: List[Dict[str, Any]]) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def append_jsonl(self, filepath: Path, item: Dict[str, Any]) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(item) + "\n")

    def load_json(self, filepath: Path) -> Dict[str, Any]:
        if not filepath.exists():
            return {}
        try:
            if filepath.stat().st_size == 0:
                return {}
        except Exception:
            pass

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return {}

        try:
            return json.loads(content)
        except Exception as e:
            import logging
            logger = logging.getLogger("memory_os.storage")
            logger.warning(f"CRITICAL: JSON file at {filepath} exists but could not be parsed: {e}")
            raise e

    def save_json(self, filepath: Path, item: Dict[str, Any]) -> None:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=2)

    def read_lines(self, filepath: Path) -> List[str]:
        if not filepath.exists():
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return f.readlines()

    def exists(self, filepath: Path) -> bool:
        return filepath.exists()

    def get_sha256(self, filepath: Path) -> str:
        if not filepath.exists():
            return ""
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
