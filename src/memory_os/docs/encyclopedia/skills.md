# Memory OS Skills

Memory OS skills are repo-local procedural modules for agents. They are not memory
nodes, not prompts, and not plugins. A skill is a small directory that tells an
agent how to perform a recurring class of work with minimal context.

## Format

Canonical local layout:

```text
skills/<skill-name>/
  SKILL.md
  references/   # optional, loaded only when needed
  scripts/      # optional deterministic helpers
  assets/       # optional reusable files/templates
  agents/       # optional UI metadata
```

`SKILL.md` must start with frontmatter:

```md
---
name: lower-hyphen-name
description: When this skill should be used.
---
```

Name constraints:

* lowercase letters/digits
* single hyphens between segments
* directory name equals `name`
* max length 64

## CLI

```bash
memory_os skills list
memory_os skills validate
memory_os skills sync --dry-run
memory_os skills sync --agent codex --agent claude --agent agy
```

`sync` copies local skills into agent-native project directories:

* Codex: `.codex/skills`
* Claude Code: `.claude/skills`
* agy/Antigravity: `.gemini/antigravity/skills`

After a real sync, Memory OS writes `memory/skills.lock.json` with installed
skill names, destinations, and content hashes.

## Design Decisions

Accepted:

* Progressive disclosure: metadata first, instructions only when active,
  resources only when needed.
* Deterministic validation before sync.
* Repo-local skill pack as the first product slice.
* Agent-native output directories instead of forcing a Memory OS-only runtime.
* Lock-like audit file for reproducibility (`memory_os skills lock`).
* Remote Git sources with ref/sub-dir pinning (`SOURCE.toml` + `skills refresh`).
* `commands/` and `mcp/` as typed, validated resource kinds alongside
  `references/`/`scripts/`/`assets/`/`agents/`.
* Managed-block injection of a skill-name/description list into `AGENTS.md`
  (`MEMORY_OS SKILLS BLOCK START/END` markers, regenerated idempotently on sync).

Deferred:

* Secret placeholder expansion.
* Global user-scope sync.

Rejected for now:

* LLM-generated skill installs without validation.
* Direct writes to global agent directories as the default.
* Storing secrets or credentials in skill packs.

## Auto-discovery reality check (verified 2026-07-06)

"Agent-native project directories" does not mean every agent actually reads
them without being told. Live-tested by giving agy a real task with zero
mention of skills, then asking directly: agy confirmed it read neither
`AGENTS.md` nor anything under `skills/` on its own. Only Claude Code has
confirmed native auto-discovery — synced skills appear in its own Skill tool
list live, no prompting needed. Codex's AGENTS.md auto-load is a documented
Codex CLI convention but was not independently re-verified in this repo, and
even if AGENTS.md loads, the injected block is name+description only — it
does not put the full `SKILL.md` body in context.

Because of this, `agent_context/agents/prompts/{claude,codex,agy}.md` (the
files actually appended to each agent's launch/dispatch command — confirmed
reliably followed, unlike AGENTS.md) each carry an explicit `## Skills`
section instructing the agent to run `memory_os skills list` and open the
matching `SKILL.md` before non-trivial work. Treat that section, not the
AGENTS.md block, as the real delivery mechanism for codex and agy.

## Initial Skill Pack

Current local skills:

* `memory-backend-audit`
* `swarm-runtime-hygiene`
* `solid-unix-portability-audit`
* `release-roadmap-audit`
* `skill-pack-maintainer`
* `systematic-debugging`, `plan`, `simplify-code`, `requesting-code-review`
  (adapted from NousResearch/hermes-agent's `software-development/*` packs;
  Hermes-specific tool calls and frontmatter fields stripped)

These cover the recurring work Memory OS already performs: memory backend
quality, swarm stability, SOLID/Unix/portability review, release-roadmap
alignment, skill pack maintenance, and general engineering process discipline.
