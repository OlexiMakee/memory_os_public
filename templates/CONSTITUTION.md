# Memory OS Development Constitution

Status: mandatory.

## Principles

1. Toolkit, not only memory.
   Memory OS exists to improve development quality: planning, context, review,
   verification, retrieval, and repeatable agent workflows.

2. Plain files first.
   Durable control-plane state should be inspectable text where possible:
   markdown, JSON, JSONL, TOML. Opaque stores are indexes or caches, not the
   source of truth.

3. SOLID boundaries.
   Keep orchestration, storage, validation, UI, and provider integrations in
   separate modules. Add interfaces before binding core code to a concrete
   external tool.

4. Unix-shaped commands.
   Commands should do one thing, support dry-run for writes when meaningful,
   and expose structured output for automation.

5. Verification before confidence.
   Specs, plans, tasks, tests, and evidence must trace to each other. Checked
   handoff items are not trusted until artifacts are verified.

6. Backward compatibility by default.
   CLI flags, JSONL schemas, and public file layouts should keep old callers
   working. New schema fields require defaults.

7. No secret capture.
   Specs, memory nodes, telemetry, and handoffs must not store raw secrets,
   tokens, credential values, or secret-bearing logs.
