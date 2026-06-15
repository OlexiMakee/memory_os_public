#!/usr/bin/env python3
import os
import sys
import uuid
from pathlib import Path

# Setup path so we can import memory_os
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.core.models import MemoryNode, MemoryEdge

def main():
    root_dir = Path(__file__).resolve().parents[1]
    
    # Init dev space config
    config = MemoryOSConfig(config_path=str(root_dir / "memory_os.config.json"), space="dev")
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    
    print(f"Ingesting project into: {config.memory_dir}")
    
    # We will clear existing dev data for a clean slate
    if config.memory_dir.exists():
        print("Clearing existing dev memory...")
        for f in config.memory_dir.glob("*.jsonl"):
            f.unlink()
        
    src_dir = root_dir / "src"
    context_dir = root_dir / "agent_context"
    
    nodes = {}
    edges = []
    
    def add_node(n_id: str, t_type: str, text: str):
        if n_id not in nodes:
            nodes[n_id] = MemoryNode(
                id=n_id,
                type=t_type,
                summary=text,
                evidence=[],
                trust="verified",
                protocol_level=90
            )

    def add_edge(src: str, tgt: str, rel: str, text: str):
        edges.append(MemoryEdge(
            source=src,
            target=tgt,
            type=rel,
            reason=text,
            confidence=1.0,
            evidence=[]
        ))

    # 1. Parse python files in src/
    print("Scanning src/")
    for path in src_dir.rglob("*.py"):
        if path.name == "__init__.py" or "pycache" in str(path):
            continue
        
        rel_path = path.relative_to(root_dir)
        n_id = str(rel_path).replace("/", "_").replace(".py", "")
        
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.splitlines()
            
        # extract classes and functions roughly
        classes = [l.split(" ")[1].split("(")[0].split(":")[0] for l in lines if l.startswith("class ")]
        funcs = [l.split(" ")[1].split("(")[0] for l in lines if l.startswith("def ")]
        
        summary = f"File: {rel_path}\nClasses: {', '.join(classes)}\nFunctions: {', '.join(funcs)[:200]}"
        
        add_node(n_id, "module", summary)
        
        # very simple dependency detection (imports)
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith("import memory_os.") or line_stripped.startswith("from memory_os."):
                if line_stripped.startswith("from memory_os."):
                    parts = line_stripped.split("from memory_os.")[1].split(" import")[0]
                else:
                    parts = line_stripped.split("import memory_os.")[1].split()[0]
                
                dep_id = "src_memory_os_" + parts.replace(".", "_")
                # Add edge to the module
                add_edge(n_id, dep_id, "depends_on", f"imports {parts}")

    # 2. Parse Markdown files in agent_context/
    print("Scanning agent_context/")
    if context_dir.exists():
        for path in context_dir.rglob("*.md"):
            rel_path = path.relative_to(root_dir)
            n_id = str(rel_path).replace("/", "_").replace(".md", "")
            
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                
            summary = f"Documentation file: {rel_path}\nPreview: {content[:200]}..."
            add_node(n_id, "document", summary)

    # Add core system node
    add_node("memory_os_core", "system", "The core memory operating system.")
    
    print(f"Saving {len(nodes)} nodes and {len(edges)} edges...")
    for n in nodes.values():
        repo.add_node(n)
        
    for e in edges:
        # only add edges if target exists
        if e.target in nodes:
            repo.add_edge(e)
            
    print("Ingestion complete!")

if __name__ == "__main__":
    main()
