# 🚀 Memory OS Quickstart

Welcome to **Memory OS**! This guide will help you build your first AI agent with a Local-First Long-Term Semantic Memory. Memory OS acts as an external hippocampus for your LLMs, keeping them grounded and focused.

## 1. Installation

For now, install Memory OS locally in editable mode:
```bash
git clone https://github.com/your-org/memory_os.git
cd memory_os
pip install -e .
```

## 2. Core Concepts

* **MemoryRepository**: The central database (SQLite + JSONL) where knowledge is kept.
* **Nodes & Edges**: Knowledge is modeled as a graph. A `MemoryNode` can be a constraint, feature, or file. A `MemoryEdge` connects them.
* **RelationPatch**: Instead of direct writes, agents submit *patches* (proposals). This allows human review and protocol-based security.
* **MemorySearcher**: Finds relevant context before sending prompts to your LLM.

## 3. Basic Example: Storing and Retrieving Rules

Let's initialize a database and teach it a basic architectural rule.

```python
from pathlib import Path
from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.core.patch import RelationPatch
from memory_os.core.search import MemorySearcher

# 1. Initialize configuration and repository
config = MemoryOSConfig(Path.cwd())
repo = MemoryRepository(FileSystemMemoryStorage(), config)

# 2. Teach Memory OS a rule via a Patch
from memory_os.core.patch import RelationPatch, RelationPatchStore

patch = RelationPatch(
    operation="upsert_node",
    source="",
    target="rule:ui_framework",
    type="constraint",
    domain="architecture",
    confidence=1.0,
    evidence=["Conversation with Lead Dev"],
    reason="Establish UI standard",
    payload={"summary": "We must only use React. No Vue or Angular."},
    created_by_protocol=0,
    required_verification_protocol=0
)

store = RelationPatchStore(repo)
patch_id = store.propose(patch)
store.apply(patch_id)

# 3. Retrieve context before prompting an LLM
searcher = MemorySearcher(config=config, repository=repo)
# Memory OS uses keyword substring search by default
results = searcher.search_memory("rule:ui_framework")

print("Found Context:")
for n in results:
    print(f"- {n.get('summary')}")
```

## 4. Visualizing the Graph

Memory OS comes with a built-in 3D Force Graph UI. Run the following command in your project root:

```bash
python3 -m memory_os ui
```
Then open `http://127.0.0.1:8099` in your browser to see your nodes and connections!

## 5. Next Steps

Check out the `examples/` directory to see how to integrate Memory OS with LiteLLM, AutoGen, CrewAI, and other frameworks using our out-of-the-box Bridges!
