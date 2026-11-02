"""
Default ActionExecutors for the vocabulary in vocabulary.py — thin
adapters from an ActionRequest's plain-dict args onto memory_os's existing
MemorySearcher/LifecycleManager/filesystem code. None of this needs a
model: an Orchestrator wired with these executors and a ScriptedActionBrain
is a real, runnable system today, with the model the only missing piece.
"""

import hashlib
import re
import threading
from typing import Any

from memory_os.agent_brain.types import ActionRequest, ActionResult
from memory_os.agent_brain.orchestrator import ActionExecutor
from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import confine_to_root, validate_safe_node_id

# One link-infer at a time — prevent N concurrent scans for N rapid writes.
_link_infer_lock = threading.Lock()


def _background_link_infer(config: MemoryOSConfig) -> None:
    """Run Stage-0 cascade link inference in a daemon thread after every write.

    Stage-0 is pure algorithmic (BM25 + structural + tags + temporal) — no LLM,
    no embeddings, no external calls. Fast enough (~100ms for 500 nodes) to run
    silently after every write without blocking the response path.
    """
    if not _link_infer_lock.acquire(blocking=False):
        return  # already running, skip — next write will re-trigger
    try:
        from memory_os.toolkit.link_inferrer import LinkInferrer
        LinkInferrer(config).run(method="cascade", resource_mode="quiet")
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)
    finally:
        _link_infer_lock.release()


def memory_search_executor(config: MemoryOSConfig) -> ActionExecutor:
    from memory_os.modules.search import MemorySearcher

    searcher = MemorySearcher(config)

    def execute(request: ActionRequest) -> ActionResult:
        query = request.args.get("query", "")
        depth = int(request.args.get("depth", 1))
        try:
            results = searcher.search_memory(query, depth=depth)
        except Exception as exc:  # search failures are data, not crashes, for an agent loop
            return ActionResult(action=request.action, ok=False, error=str(exc))
        return ActionResult(action=request.action, ok=True, data=results)

    return execute


def _csv_arg(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _agent_node_id(summary: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", summary.lower()).strip("-._")[:48] or "note"
    digest = hashlib.sha1(summary.encode("utf-8")).hexdigest()[:8]
    return f"agent:{slug}-{digest}"


def memory_write_executor(config: MemoryOSConfig) -> ActionExecutor:
    from memory_os.modules.lifecycle import LifecycleManager, PROMOTABLE_NODE_TYPES
    from memory_os.modules.search import MemorySearcher, VERBATIM_QUERY_SCORE

    lifecycle = LifecycleManager(config)
    searcher = MemorySearcher(config)

    def _find_duplicate(summary: str, node_type: str) -> Any:
        """Return an existing node dict if a near-duplicate is found, else None.

        Uses the existing search pipeline (BM25/FTS5). A score at the shared
        verbatim-query boundary means the summary contains the query exactly.
        Skips stale/archived/superseded nodes.
        """
        try:
            results = searcher.search_memory(summary, depth=0)
            for r in results:
                if r.get("type") not in PROMOTABLE_NODE_TYPES:
                    continue
                if r.get("status") in ("stale", "superseded", "archived"):
                    continue
                if r.get("search_score", 0.0) >= VERBATIM_QUERY_SCORE:
                    return r
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
        return None

    def execute(request: ActionRequest) -> ActionResult:
        args = request.args
        summary = str(args.get("summary") or args.get("content") or args.get("text") or args.get("rule") or args.get("fact") or "").strip()
        if not summary:
            return ActionResult(action=request.action, ok=False, error="memory.write requires a non-empty summary/content arg")

        node_type = str(args.get("type") or "fact").strip()
        if node_type not in PROMOTABLE_NODE_TYPES:
            return ActionResult(action=request.action, ok=False, error=f"invalid memory.write type: {node_type!r}")

        # Dedup check: avoid writing facts that already exist verbatim.
        # Only fires when no explicit node_id is given (agent-generated writes).
        explicit_id = str(args.get("id") or "").strip()
        if not explicit_id:
            dupe = _find_duplicate(summary, node_type)
            if dupe:
                return ActionResult(
                    action=request.action,
                    ok=True,
                    data={"node_id": dupe["id"], "status": "deduped",
                          "existing_summary": str(dupe.get("summary", ""))[:80]},
                )

        node_id = explicit_id or _agent_node_id(summary)
        try:
            validate_safe_node_id(node_id)
            code = lifecycle.propose(
                node_id=node_id,
                node_type=node_type,
                summary=summary,
                evidence=_csv_arg(args.get("evidence")),
                tags=_csv_arg(args.get("tags")),
            )
        except Exception as exc:
            return ActionResult(action=request.action, ok=False, error=str(exc))

        if code == 0:
            # Background Stage-0 link inference — connects the new node to the graph.
            # Daemon thread: won't block response or process exit.
            threading.Thread(
                target=_background_link_infer, args=(config,), daemon=True
            ).start()

        return ActionResult(action=request.action, ok=(code == 0), data={"node_id": node_id, "status": "draft"})

    return execute


def file_read_executor(config: MemoryOSConfig) -> ActionExecutor:
    def execute(request: ActionRequest) -> ActionResult:
        path = request.args.get("path", "")
        try:
            resolved = confine_to_root(path, config.root_dir)
            text = resolved.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return ActionResult(action=request.action, ok=False, error=str(exc))
        return ActionResult(action=request.action, ok=True, data=text)

    return execute


def default_executors(config: MemoryOSConfig):
    """Convenience bundle matching default_memory_os_vocabulary() 1:1."""
    return {
        "memory.search": memory_search_executor(config),
        "memory.write": memory_write_executor(config),
        "file.read": file_read_executor(config),
    }
