---
name: plan
description: Write concrete, actionable implementation plans in markdown.
---

# Actionable Planning

Core Principle: When requested to plan or preview work, produce a clear, concrete implementation plan before modifying any project code files.

## Plan Structure
Every plan must include:
1. **Goal**: A clear statement of the objective.
2. **Context & Assumptions**: Current state of the codebase and dependencies.
3. **Proposed Approach**: Architectural decisions, alternatives considered, and risks.
4. **Task Breakdown**: Sequenced, bite-sized tasks (each taking 2-5 minutes of work).
5. **Validation & Verification**: The exact test commands and manual verification steps to run.

## Task Design
- Define task boundaries explicitly.
- For each step, include expected inputs, modified files/paths, and checkable success criteria.
- Prefer a Test-Driven Development (TDD) order: write test first, run to verify it fails, write code to pass, commit.

## Save Location
- For non-trivial feature work, use the existing spec workflow: `memory_os spec init "<title>"` creates `specs/NNN-slug/{spec.md,plan.md,tasks.md}` — write the plan there, not in an ad-hoc location.
- For a quick one-off plan not worth a full spec, a scratch markdown file is fine, but check `specs/` first so plans stay traceable in one place.
