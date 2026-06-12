# Memory OS (Portable Core)

**Memory OS extends an LLM beyond its context window by giving it a local, indexed, protocol-governed long-term memory graph.**

It is a local-first long-term semantic memory prosthesis for LLM agents. Instead of forcing the LLM to remember everything in its limited context window, Memory OS stores knowledge as explicitly linked nodes, relations, evidence, metadata, and lifecycle states. It acts as an external hippocampus—retrieving only the relevant context precisely when the agent needs it.

> *LLM shouldn't remember everything. It should know how to ask Memory OS.*

## Standalone Usage

This directory (`memory_os/`) is completely self-contained. It only relies on the Python standard library. It does not import anything from the host product (`news-scraper` or otherwise).

### Moving to a New Agent Project
To transfer Memory OS to another agent project:
1. **Copy the directory:** Simply copy this entire `memory_os/` directory into the root of your new project.
2. **Add CLI Entry Point:** If you want the `memory_os` CLI to be available globally in the new project's virtual environment, add the following to your new project's `pyproject.toml`:
   ```toml
   [project.scripts]
   memory_os = "memory_os.cli:main"
   ```
   Then run `pip install -e .` in the new project.
3. **If developing as a standalone package:** 
   Rename `STANDALONE_pyproject.toml` to `pyproject.toml` and move it to the *parent directory* alongside the `memory_os` folder, giving you a standard Python package structure.

### Testing
All internal tests for Memory OS are located in `memory_os/tests/`. To run them (from the root of the project where `memory_os` is placed):
```bash
python -m unittest discover -s memory_os/tests
```

### Architecture
See `docs/ARCHITECTURE.md` (if exported) for full system design, or review `core/repository.py` to see how the Domain models (`MemoryNode`, `MemoryEdge`, `TaskCapsule`) are persisted to `IMemoryStorage`.
