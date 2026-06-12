import ast
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from memory_os.core.adapters import CodebaseDomainAdapter

class ContextRegistry:
    """Standalone developer memory indexing engine. Builds compact context snapshots."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.adapter = CodebaseDomainAdapter()

    def rel(self, path: Path) -> str:
        """Get relative path string."""
        try:
            return str(path.relative_to(self.root_dir))
        except ValueError:
            return str(path)

    @staticmethod
    def redact(text: str) -> str:
        """Redact potential secrets and credentials from index files."""
        secret_patterns = (
            re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
            re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"',}]+"),
            re.compile(r"postgresql://[^\s'\"]+"),
        )
        redacted = text
        for pattern in secret_patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    @staticmethod
    def sha256_text(text: str) -> str:
        """Compute short SHA-256 checksum."""
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def layer_for(self, path: Path) -> str:
        """Identify architectural layers (meta, telemetry, domain)."""
        try:
            parts = set(path.relative_to(self.root_dir).parts)
        except ValueError:
            parts = set(path.parts)
        name = path.name.lower()
        if "agent_context" in parts or "configs" in parts or name in {"readme.md", "index.md"}:
            return "meta-layer"
        if "agent_proposals" in parts or "logs" in parts or path.suffix == ".log":
            return "telemetry-layer"
        return "domain-layer"

    def iter_files(self, paths: Iterable[str], include_telemetry: bool, excluded_dirs: set, text_suffixes: set) -> Iterable[Path]:
        """Iterate files traversing directories recursively."""
        for item in paths:
            base = (self.root_dir / item).resolve()
            if not base.exists():
                continue
            candidates = [base] if base.is_file() else base.rglob("*")
            for path in candidates:
                if not path.is_file():
                    continue
                try:
                    rel_parts = path.relative_to(self.root_dir).parts
                except ValueError:
                    rel_parts = path.parts
                if any(part in excluded_dirs for part in rel_parts):
                    continue
                if path.suffix.lower() not in text_suffixes:
                    continue
                if self.layer_for(path) == "telemetry-layer" and not include_telemetry:
                    continue
                yield path

    @staticmethod
    def compact_whitespace(text: str, max_chars: int) -> str:
        """Strip spaces and shorten string."""
        return re.sub(r"\s+", " ", ContextRegistry.redact(text)).strip()[:max_chars]



    def build_pointer(self, path: Path, text: str, max_preview_chars: int) -> Dict[str, Any]:
        """Construct layer pointer mappings."""
        suffix = path.suffix.lower()
        meta: Dict[str, Any] = {
            "layer": self.layer_for(path),
            "file": self.rel(path),
            "bytes": path.stat().st_size,
            "sha256_16": self.sha256_text(text),
        }
        if suffix in {".py", ".js"}:
            meta.update(self.adapter.extract_metadata(path.name, text))
        elif suffix in {".md", ".txt"}:
            headings = re.findall(r"^(#{1,4})\s+(.+)$", text, flags=re.MULTILINE)
            meta["headings"] = [title.strip() for _, title in headings[:20]]

        vector_text = " ".join([
            self.rel(path),
            " ".join(meta.get("functions", [])),
            " ".join(meta.get("classes", [])),
            " ".join(meta.get("headings", [])),
            self.compact_whitespace(text, max_preview_chars),
        ])
        return {
            "vector_text": self.compact_whitespace(vector_text, max_preview_chars * 2),
            "meta": meta,
        }

    def build_snapshot(
        self,
        paths: List[str],
        include_telemetry: bool = False,
        max_items: int = 160,
        max_file_bytes: int = 220000,
        max_preview_chars: int = 360
    ) -> Dict[str, Any]:
        """Generate structured context nodes list."""
        excluded_dirs = {".git", ".tmp.driveupload", ".venv", "venv", "venv_auto", "node_modules", "__pycache__", ".pytest_cache", "data"}
        text_suffixes = {".md", ".txt", ".json", ".jsonl", ".py", ".js", ".css", ".html", ".sql", ".yml", ".yaml", ".toml"}

        items = []
        skipped = []
        for path in self.iter_files(paths, include_telemetry, excluded_dirs, text_suffixes):
            try:
                if path.stat().st_size > max_file_bytes:
                    skipped.append({"file": self.rel(path), "reason": "too-large"})
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                skipped.append({"file": self.rel(path), "reason": f"error: {e}"})
                continue
            
            items.append(self.build_pointer(path, text, max_preview_chars))
            if len(items) >= max_items:
                break

        from collections import Counter
        layer_counts = Counter(item["meta"]["layer"] for item in items)
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds") if hasattr(datetime, "now") else "2026-06-01T00:00:00",
            "root": str(self.root_dir),
            "counts": {
                "items": len(items),
                "skipped": len(skipped),
                "layers": dict(layer_counts),
            },
            "items": items,
            "skipped": skipped[:50],
        }
