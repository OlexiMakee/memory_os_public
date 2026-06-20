# templates/scripts/

Scaffold scripts for the **LOCAL FIRST** principle.

## What is LOCAL FIRST?

Agents must never write ad-hoc SQL queries, one-off Python scripts, or inline
shell commands to answer analytical questions. Instead:

1. Build a CLI tool once (`scripts/<domain>_engine.py`)
2. Write a project skill or rules file from `templates/skills/local_first_skill_template.md`
3. Commit both to memory_os so every downstream project inherits the pattern

This eliminates token waste, inconsistency, and hidden bugs from throwaway code.

## Files

| File | Purpose |
|------|---------|
| `local_first_engine_template.py` | Copy → `scripts/<domain>_engine.py`, replace stub logic with real modules |
| `../skills/local_first_skill_template.md` | Copy into a project skill/rules directory for new tools |
| `../skills/examples/analytics_engine_skill.md` | Example of a domain-specific LOCAL FIRST skill |

## Real-world example

`scripts/analytics_engine.py` in news-research projects implements this pattern
with three commands: `trends` (anomaly detection), `top` (ranking), `tags` (phrase analysis).
Its example skill file lives at `templates/skills/examples/analytics_engine_skill.md`.

## How to create a new LOCAL FIRST tool

1. Copy `local_first_engine_template.py` → `scripts/<domain>_engine.py`
2. Replace stub imports and logic with your project's modules
3. Copy `templates/skills/local_first_skill_template.md` → `<project-skill-dir>/<domain>_engine_skill.md`
4. Update the skill file: trigger, rule, commands, notes
5. Commit both files
