#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from memory_os.core.adapters import DomainAdapterIngestor
from memory_os.core.config import MemoryOSConfig
from memory_os.core.models import MemoryNode
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage


def main() -> None:
    config = MemoryOSConfig(config_path=str(ROOT_DIR / "memory_os.config.json"), space="dev")
    repository = MemoryRepository(FileSystemMemoryStorage(), config)

    print(f"Ingesting project into: {config.memory_dir}")
    print("Resetting canonical dev graph through patch store...")
    repository.replace_edges([])
    repository.replace_nodes([])

    result = DomainAdapterIngestor(repository).ingest_python_tree(
        ROOT_DIR / "src",
        ROOT_DIR,
    )

    context_dir = ROOT_DIR / "agent_context"
    document_count = 0
    if context_dir.exists():
        for path in sorted(context_dir.rglob("*.md")):
            relative_path = path.relative_to(ROOT_DIR)
            node_id = relative_path.as_posix().removesuffix(".md").replace("/", "_")
            content = path.read_text(encoding="utf-8")
            repository.upsert_node(
                MemoryNode(
                    id=node_id,
                    type="document",
                    summary=f"Documentation file: {relative_path}\nPreview: {content[:200]}...",
                    evidence=[relative_path.as_posix()],
                    trust="verified",
                    protocol_level=90,
                )
            )
            document_count += 1

    repository.upsert_node(
        MemoryNode(
            id="memory_os_core",
            type="system",
            summary="The core memory operating system.",
            evidence=[],
            trust="verified",
            protocol_level=90,
        )
    )
    print(
        "Ingestion complete: "
        f"{result['files_indexed']} Python files, "
        f"{result['operations_applied']} code graph operations, "
        f"{document_count} documents."
    )


if __name__ == "__main__":
    main()
