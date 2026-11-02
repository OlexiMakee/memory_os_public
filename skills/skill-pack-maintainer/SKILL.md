---
name: skill-pack-maintainer
description: Maintain Memory OS skill packs under skills/.
allowed-tools:
  - shell
  - git
---

# Skill Pack Maintainer

Core Principle: Enforce consistent structure, progressive disclosure, and validation discipline when adding or modifying skills.

## Structure Rules
1. **Location**: Each skill must live in `skills/<name>/`, where `<name>` is lowercase segments separated by single hyphens matching the YAML frontmatter `name`.
2. **SKILL.md**: Mandatory file with frontmatter:
   ```yaml
   ---
   name: name-of-skill
   description: One-line explanation of when to use.
   ---
   ```
3. **Resource Delegation**: Keep `SKILL.md` short and behavioral. Place details in folders:
   - `references/`: Extended workflows and references.
   - `scripts/`: Helper scripts and tools.
   - `assets/`: Reusable files.
   - `commands/`: Slash-command definitions (`*.md` only).
   - `mcp/`: Valid JSON MCP manifests (`*.json` only).

## Remote Pinning (`SOURCE.toml`)
If external, add `SOURCE.toml` to the skill directory:
```toml
repo = "git-url"
ref = "branch-or-tag-or-sha"
subdir = "path-inside-repo"
```

## CLI Reference
- **Validate**: `python3 -m memory_os skills validate`
- **Sync**: `python3 -m memory_os skills sync [--agent <name>] [--dry-run]`
- **Lock**: `python3 -m memory_os skills lock`
- **Refresh**: `python3 -m memory_os skills refresh <name> [--all]`

## Completion Checklist
- [ ] Directory name matches frontmatter `name`.
- [ ] All code block instructions are agent-agnostic (no model-specific tools).
- [ ] Run validate, lock, and sync commands successfully.
- [ ] Sync automatically updates the managed instruction block in `AGENTS.md`.
