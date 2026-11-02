---
name: memory-backend-audit
description: Audit and improve Memory OS memory backend quality: patch-store write path, lifecycle gates, retrieval evals, deduplication, timecodes, and graph health. Use for backend-first memory work before UI work.
allowed-tools:
  - shell
  - git
---

# Memory Backend Audit

Use this skill inside the Memory OS repository.

Start with:

```bash
python3 -m memory_os search "memory backend patch store lifecycle retrieval eval graph health"
python3 -m memory_os memory health
python3 -m memory_os eval run retrieval-relevance --format json
```

Audit in this order:

1. Write path: graph mutations must go through `RelationPatchStore`, not direct live `nodes.jsonl` or `edges.jsonl` rewrites.
2. Lifecycle: low-confidence candidates stay draft; hard schema/evidence violations become stale; explicit promote/reject remains available.
3. Retrieval: compare precision@5 and recall@5 before tuning thresholds.
4. Maintenance: inspect dedup candidates, stale index repair, pinned-node guards, and event/patch log size signals.
5. Portability: backend code must stay stdlib-first unless a dependency is already optional.

Output findings first. If editing, keep changes scoped and run:

```bash
python3 -m pytest tests/ -x -q
```
