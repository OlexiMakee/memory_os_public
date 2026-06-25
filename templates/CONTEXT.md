# Project Context

Project: [YOUR PROJECT NAME]
State: [One-line description of what this project does]
Runtime: [OS, language, runtime, key deps]

## Single Source of Truth (SSOT)
- **Root**: This directory is the authoritative source for this project's agent context.
- **Enforcement**: All architectural changes MUST be committed here before agents act on them.
- **Scope**: This file describes THIS project only. Do not import context from other projects.

## Core Architecture
- **Concept**: [What problem does this solve? One sentence.]
- **Data Model**: [Key entities and how they relate]
- **Storage**: [Where data lives — files, DB, etc.]
- **Entry Points**: [Main CLI commands or API surface]

## Common Commands
```bash
# [describe what this does]
[command]

# [describe what this does]
[command]
```

## Environment Variables
Never print `.env` values. Required vars:
- `VAR_NAME` — [what it's for]

## Known Risks & Guidelines
- [Key constraint or gotcha agents must know]
- [Another constraint]

## Upstream Updates
- **Check for updates**: Run `python3 -m memory_os check-updates`.
- **Public-facing fixes**: Use the public repository's normal issue/PR flow for reusable changes. Keep private planning files and internal strategy notes on private remotes only.
