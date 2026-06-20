# Skill: Analytics Engine
> **Example of a LOCAL FIRST skill script.** See Section 2 for how to create similar skills for other tools.

---

## Section 1 — How to use this skill

**Trigger:** User asks for trends, top videos, keyword/tag analysis, viral content, or any channel performance data.

**Rule:** Do NOT write ad-hoc analysis scripts or SQL queries. Always call `scripts/analytics_engine.py`.

### Commands

#### trends — anomaly / viral detection
```bash
python scripts/analytics_engine.py trends --channel <NAME> [--threshold 2.5] [--output markdown|json]
```
Use for: "what's going viral", "anomaly detection", "що треба алертити".

#### top — top N videos by metric
```bash
python scripts/analytics_engine.py top --channel <NAME> --metric views|likes|comments|engagement --limit 10 --days 30 [--output markdown|json]
```
Use for: "топ відео за тиждень", "most liked videos", "best engagement".

#### tags — keyword / phrase performance
```bash
python scripts/analytics_engine.py tags --channel <NAME> --ngram 2 --limit 20 --sort-metric view_count [--days 30] [--output markdown|json]
```
Use for: "які теми працюють", "keyword performance", "what topics drive views".

### Notes
- `--channel` accepts name, handle, or ID.
- Omit `--channel` in `tags` to analyze all channels.
- Default DB: `data/youtube_news.db` (auto-resolved from project root).
- Default output: `markdown`. Use `--output json` for programmatic parsing.
- For deeper analysis (topic study, KPI dashboard, method evaluation) use `scripts/analytics/cli.py` directly.

---

## Section 2 — LOCAL FIRST principle: how to create skill scripts for other tools

This file is a **template**. Every reusable agent capability in this project should follow the same pattern.

### Why LOCAL FIRST?
Agents writing ad-hoc SQL queries, one-off Python scripts, or inline shell commands creates:
- Token waste (re-deriving the same logic every session)
- Inconsistency (different agents produce different results for the same question)
- Hidden bugs (untested throwaway code)
- Violation of DRY

The fix: build a CLI tool once, write a skill file that teaches agents to call it.

### Template for a new skill script

Create `<project-skill-dir>/<tool_name>_skill.md` with this structure:

```markdown
# Skill: <Tool Name>

**Trigger:** <When should an agent use this? What user requests match?>

**Rule:** Do NOT <what to avoid>. Always use `<path/to/tool.py>`.

## Commands

### <command-name> — <one-line description>
\`\`\`bash
python <path/to/tool.py> <command> --<required-arg> <VALUE> [--<optional-arg> <DEFAULT>]
\`\`\`
Use for: "<example user request 1>", "<example user request 2>".

## Notes
- <Gotcha 1>
- <Gotcha 2>
- <Where to find deeper functionality if this tool is not enough>
```

### Checklist before creating a new skill

1. **Does a CLI tool exist?** If not, build it first (`scripts/<name>.py` with Click or argparse). The skill file is only a pointer — without the tool it's useless.
2. **Is the tool idempotent and safe to call autonomously?** Read-only tools are always safe. Write tools need a `--dry-run` flag.
3. **Does the tool output both `--output markdown` and `--output json`?** Markdown for human display, JSON for chaining into other tools.
4. **One trigger sentence.** The agent must be able to match user intent to this tool in one sentence. If you need three sentences to explain when to use it, split into two tools.
5. **One rule sentence.** What must the agent NOT do instead? (e.g. "do not write ad-hoc SQL").

### Examples of LOCAL FIRST tools to build next
- `scripts/brief_engine.py` — generate editorial briefs from CLI instead of ad-hoc LLM calls
- `scripts/source_inspector.py` — inspect source registry, run readiness checks
- `scripts/anomaly_reporter.py` — standalone anomaly report with Slack/Telegram output
