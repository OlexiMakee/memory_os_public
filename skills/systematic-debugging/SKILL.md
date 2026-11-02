---
name: systematic-debugging
description: 4-phase root cause debugging. Understand bugs before fixing.
---

# Systematic Debugging

Core Principle: ALWAYS identify the root cause before attempting any code changes. Never apply quick symptom-level patches that mask underlying issues.

## Phase 1: Root Cause Investigation
1. Build a tight reproduction loop (e.g. failing test, CLI invocation, curl command) that fails deterministically on the bug.
2. Trace the data flow and stack trace to find the origin of the invalid state.
3. Check recent git history (`git log -p`) or config changes.
4. Ensure the repro loop is RED before proceeding. Do NOT write any code fixes yet.

## Phase 2: Formulate Hypothesis
1. Write down a clear theory explaining the root cause based on gathered evidence.
2. Confirm the theory matches all observed symptoms.

## Phase 3: Implement & Validate
1. Implement the minimal fix addressing the root cause directly.
2. Run the reproduction loop to verify it turns GREEN.
3. Run the full test suite (`python -m pytest tests/ -x -q`) to ensure no regressions.

## Phase 4: Defense-in-Depth
1. Add a permanent regression unit/integration test.
2. Remove any temporary print statements or debug logs.
3. Commit changes with a clear explanation of both the symptom and the root cause.
