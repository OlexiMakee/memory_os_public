# Agent Rules

Status: mandatory. Language: concise English.

## Behavior
- No default praise. Use critical, project-aware analysis.
- Offer options only when choices matter.
- State assumptions, risks, verification, and remaining gaps.
- Keep docs and handoffs short. Remove narrative.

## Autonomy
Allowed without approval:
- Read/search project files.
- Small scoped code edits.
- Non-destructive backend checks: compile, test client, API smoke tests.
- Run unit and integration tests autonomously after edits.

Ask first:
- Destructive file or DB actions.
- DB schema or migration changes.
- New dependencies.
- Secret handling beyond `.env` placeholders.
- Large refactors or architecture changes.
- Long-running, network-heavy, or paid external operations.

## Handshake Verification (MANDATORY)
Every time you read `agent_context/HANDSHAKE.md`, you MUST verify that `[x]` items are actually implemented:
- Check that key files exist (`ls`, `find`).
- Check that key functions/routes are present (`grep`).
- Flag any item marked `[x]` whose artifact is missing — correct the checkbox to `[ ]` and note the gap.

Do NOT trust the checkbox alone. The handshake can go stale or contain optimistic entries from previous sessions.

## Token-Budget And Step Tiers
- Step scale: 1–12 (`nano` → `giant`).
- Accept triggers like `product 7`, `memory tiny`, `giant steps`.
- Adjust response density, edit scope, and autonomy to the declared tier.
