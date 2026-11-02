---
name: requesting-code-review
description: Pre-commit verification checklist: security scan, quality gates, and self-review.
---

# Pre-Commit Code Verification

Core Principle: Verify all code modifications against security, lint, and test suites before committing or submitting a pull request.

## Step 1: Security Scan
Scan added code lines (using `git diff`) to ensure no security issues:
- No hardcoded API keys, secrets, or passwords.
- No shell injection vectors (avoid `shell=True` in subprocesses).
- No dangerous dynamic evaluation (`eval` or `exec`).
- Safe deserialization (avoid unsafe `pickle`).

## Step 2: Quality Gates
1. Run local linters and type checkers (e.g. `ruff`, `mypy`) to ensure code compliance.
2. Run the test suite: `python -m pytest tests/ -x -q`.
3. Ensure no regressions compared to the repository baseline.

## Step 3: Self-Review Checklist
- [ ] No hardcoded secrets or configs.
- [ ] Error handling is added for network/I/O boundaries.
- [ ] Commented-out code and debug print statements are removed.
- [ ] New functionality is covered by unit or integration tests.
