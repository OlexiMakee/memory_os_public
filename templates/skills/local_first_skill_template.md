# Skill: <Tool Name>

Status: template.

## Trigger

Use this skill when the user asks for a recurring analysis or operational workflow that should be handled by a committed project CLI instead of ad-hoc code.

## Rule

Do not recreate the workflow with one-off scripts, SQL, or inline shell pipelines when the project has a matching engine. Use `scripts/<domain>_engine.py`.

## Commands

### detect

```bash
python scripts/<domain>_engine.py detect --source <SOURCE> --threshold 2.5 --output markdown
```

Use for anomaly, outlier, alert, or "what changed" requests.

### rank

```bash
python scripts/<domain>_engine.py rank --source <SOURCE> --metric <METRIC> --limit 10 --days 30 --output markdown
```

Use for top-N, best/worst, leaderboard, or metric comparison requests.

### tags

```bash
python scripts/<domain>_engine.py tags --source <SOURCE> --ngram 2 --limit 20 --days 30 --output markdown
```

Use for keyword, phrase, topic, or grouping requests.

## Safety

- Prefer read-only commands for autonomous runs.
- Write commands must expose `--dry-run` and should be documented separately.
- Use `--output json` when another tool will consume the result.
- Keep default paths project-local and avoid credentials in output.

## Adaptation Checklist

1. Replace `<Tool Name>`, `<domain>`, `<SOURCE>`, and `<METRIC>`.
2. Document every command the engine supports.
3. Add examples in the user's project language if needed.
4. Remove unused commands from this template.
