---
name: simplify-code
description: Review and simplify recent code changes for reuse, quality, and efficiency.
---

# Simplify Code

Core Principle: Systematically inspect recent changes to eliminate redundant code, improve readability, and optimize performance before finalizing changes.

## Phase 1: Diff Identification
Identify the changes to review:
- For unstaged changes: `git diff`
- For staged/committed changes: `git diff HEAD` or `git diff HEAD~1`

## Phase 2: Multi-Angle Review
Inspect the diff against the following criteria:
1. **Code Reuse**: Search the codebase (using `memory_os search` or grep) for existing helpers, utilities, or constants that can replace the newly introduced logic.
2. **Quality & Readability**: Simplify nested conditions, ensure consistent variable naming, and remove commented-out code or debug statements.
3. **Efficiency**: Check for unnecessary database queries, redundant loops, or heavy allocations.

## Phase 3: Validation
- Apply simplifications.
- Run the full test suite (`python -m pytest tests/ -x -q`) to verify no behavior has changed.
