# Audit 2: lifecycle.py and compactor.py

Scope:
- `src/memory_os/modules/lifecycle.py`
- `src/memory_os/modules/compactor.py`

Reviewed supporting code paths:
- `src/memory_os/modules/validator.py` (`EvolutionGate`, `VALID_EDGE_TYPES`)
- `src/memory_os/modules/exporter.py` (`PolyglotExporter`)
- `src/memory_os/core/storage.py`
- `src/memory_os/core/models.py`
- `src/memory_os/core/repository.py`

## Finding 1: LLM-proposed node IDs are used as filesystem paths before safe-ID validation

- Severity: high
- File: `src/memory_os/modules/compactor.py:421`
- File: `src/memory_os/modules/compactor.py:604`
- File: `src/memory_os/modules/lifecycle.py:188`
- Called path: `src/memory_os/modules/exporter.py:36`
- Called path: `src/memory_os/modules/exporter.py:62`
- Called path: `src/memory_os/modules/exporter.py:68`
- Called path: `src/memory_os/modules/exporter.py:103`

`MemoryCompactor` accepts LLM-proposed node IDs after `EvolutionGate`, but `EvolutionGate` only checks that `id` is non-empty, not that it is a safe single path segment. Accepted node IDs are then passed to `PolyglotExporter.export_node()` in both `compact_capsules()` and `compress_graph()`. The exporter constructs paths directly from `node_id`, including `.cursor/rules/{node_id}.mdc`, `agent_context/knowledge/{node_id}`, `artifacts/{node_id}_details.md`, and `.claude/skills/{node_id}.md`.

`LifecycleManager._emit_skill_file()` repeats the same pattern for verified rule nodes, building `.claude/skills/{node['id']}.md` directly.

Concrete exploit scenario:

1. The compaction LLM returns an otherwise valid rule node with:

   ```json
   {
     "id": "../../AGENTS",
     "type": "rule",
     "summary": "Malicious persistent agent instruction content long enough to pass quality checks.",
     "evidence": ["agent_context/task_capsules.jsonl"]
   }
   ```

2. Two critics return `"approve"` for that node. The critic prompt reviews durability, summary quality, and evidence plausibility; it does not review path safety.
3. `EvolutionGate._schema_check()` accepts the ID because it only requires a non-empty `id`.
4. `compact_capsules()` reaches `compactor.py:421-422`, or `compress_graph()` reaches `compactor.py:604-605`, and calls `PolyglotExporter`.
5. `exporter.py:103` resolves `.claude/skills/../../AGENTS.md`, which targets the workspace-level `AGENTS.md`. The exporter writes attacker-controlled Markdown there.
6. If the node later transitions as a rule, `lifecycle.py:188` and `lifecycle.py:196` write the same unsafe path pattern again.

This is not critic-verdict path injection: critic verdict fields are only logged as event metadata. The vulnerable fields are LLM-proposed node IDs that pass the critic panel and gate.

Suggested fix:

- Validate every externally generated node ID before any write using the existing `memory_os.core.safe_id.validate_safe_id()` helper.
- Apply the same validation in `EvolutionGate._schema_check()`, `LifecycleManager.propose()`, `LifecycleManager._emit_skill_file()`, and `PolyglotExporter.export_node()` as defense in depth.
- For exporter paths, additionally resolve the final path and require it to stay inside the intended export directory before opening it.
- Reject IDs containing `/`, `\`, absolute paths, empty segments, or leading `.`.

## Finding 2: Destructive override/refute edges are not reviewed by the critic panel and can prune existing verified nodes

- Severity: high
- File: `src/memory_os/modules/compactor.py:239`
- File: `src/memory_os/modules/compactor.py:245`
- File: `src/memory_os/modules/compactor.py:384`
- File: `src/memory_os/modules/compactor.py:393`
- File: `src/memory_os/modules/compactor.py:617`
- File: `src/memory_os/modules/compactor.py:623`
- Destructive sink: `src/memory_os/modules/lifecycle.py:153`
- Destructive sink: `src/memory_os/modules/lifecycle.py:164`
- Destructive sink: `src/memory_os/modules/lifecycle.py:264`
- Destructive sink: `src/memory_os/modules/lifecycle.py:286`

The 3-critic panel only votes on proposed nodes. `_process_single_batch()` returns `proposed_edges` unchanged after the node vote. In `compact_capsules()`, those unreviewed edges are appended if `source`, `target`, and `type` are present, the type is in `VALID_EDGE_TYPES`, and both endpoints exist in `all_ids`. This allows an LLM to append an `overrides` or `refutes` edge between two already-existing verified nodes even if all proposed nodes were rejected.

`compress_graph()` has a related issue: after node voting and `EvolutionGate`, it appends proposed edges whose source is an accepted new node and target is an existing node, but it does not require the edge type to be `overrides`, does not revalidate the edge type against `VALID_EDGE_TYPES`, and does not require critic approval for the edge's target set. The dry-run mode exists, but the default path is destructive and immediately calls `lifecycle.transition()`, `prune()`, and `manifest()`.

Concrete failure scenario for `compact_capsules()`:

1. Existing graph has two verified nodes: `current.rule` and `important.policy`.
2. The compaction LLM returns no acceptable nodes, but includes this edge:

   ```json
   {
     "source": "current.rule",
     "target": "important.policy",
     "type": "refutes"
   }
   ```

3. The critic panel rejects every proposed node, but the edge is still present in `result["proposed_edges"]`.
4. `compact_capsules()` accepts the edge at `compactor.py:384-393` because both IDs already exist and `refutes` is a valid edge type.
5. The edge is appended at `compactor.py:423-425`.
6. `lifecycle.transition()` sees a verified source and sets the target to `stale` at `lifecycle.py:153-164`.
7. `lifecycle.prune()` removes the stale target from `nodes.jsonl` at `lifecycle.py:264-286` and archives its connected edges.

Concrete failure scenario for `compress_graph()`:

1. Existing graph has verified nodes `old.a`, `old.b`, and unrelated `critical.rule`.
2. The compression LLM proposes a merged node `merged.a_b` that passes 2 of 3 critics and `EvolutionGate`.
3. The same response also includes:

   ```json
   {
     "source": "merged.a_b",
     "target": "critical.rule",
     "type": "refutes"
   }
   ```

4. `compress_graph()` appends the edge at `compactor.py:617-623` because `source` is a new accepted node and `target` exists.
5. The new node is promoted to verified by `lifecycle.transition()`.
6. The `refutes` edge marks `critical.rule` as `stale`, and `prune()` removes it.

This means irreversible deletion is not gated on confirmation from all three critics. It is not even gated on critic review of edges. In `compact_capsules()`, a destructive edge between existing nodes can survive with zero accepted proposed nodes.

Suggested fix:

- Treat edges as first-class reviewed artifacts. Include proposed edges in the critic prompt and require explicit approval for each edge.
- In `compact_capsules()`, reject `overrides` and `refutes` edges unless their source is a newly accepted node from the same batch and their destructive target set has been approved.
- In `compress_graph()`, only allow `type == "overrides"` for compression edges, require `source` to be an accepted merged node, require `target` to be one of the verified nodes actually represented in that merged node's evidence/merge plan, and reject all other edge types.
- Make destructive graph compression dry-run by default or require an explicit `--apply`/confirmation flag before calling `transition()` and `prune()`.
- Before pruning, emit a plan containing the exact node IDs that will be superseded or staled, then verify that the plan matches critic-approved edge decisions.

## No confirmed issue: lifecycle override-chain ordering

I did not find a current ordering bug in `LifecycleManager.transition()` for transitive override/refute chains. The method snapshots pre-existing verified IDs at `lifecycle.py:97-100`, records newly verified IDs at `lifecycle.py:123-127`, and evaluates override/refute sources against `all_verified_ids` at `lifecycle.py:148-159`. Because `all_verified_ids` is stable and independent of the later mutation of `updated_nodes`, a chain like `A overrides B` and `B overrides C` still sees both `A` and pre-verified `B` as verified sources even if `B` is marked `superseded` earlier in the edge loop.

I also did not find code in `lifecycle.py` that writes an invalid node status value. The statuses assigned in the reviewed transition/prune path are `stale`, `verified`, and `superseded`, which are valid statuses per `MemoryValidator.validate_nodes()`.

## No confirmed issue: critic verdicts as commands or paths

I did not find any code path where LLM-returned critic verdict strings are used to construct a file path, execute a command, or control anything other than classification and event logging. `_panel_vote()` only increments approval counts for exact `"approve"` verdicts at `compactor.py:181-183`. Critic reasons and verdict-derived statuses are written into event records at `compactor.py:395-405` and `compactor.py:561-571`.

The path issue above is instead caused by LLM-proposed node IDs, not critic verdict fields.

## No confirmed issue: graph traversal recursion or cyclic graph hang

I did not find unbounded recursion in either scoped module. The reviewed graph operations are bounded loops over loaded `nodes`, `edges`, task capsule batches, and LLM result arrays. `lifecycle.transition()` does not recursively traverse edges; it scans the edge list once. `compress_graph()` sends all verified node summaries to an LLM in one payload, which can be large, but it is not a cyclic graph traversal or stack-overflow risk in the local code path.

VERDICT: 2 issues found (2 critical/high)
