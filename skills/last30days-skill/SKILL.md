---
name: last30days-skill
description: "AI-ресерчер, що аналізує тренди за 30 днів у різних соцмережах."
---

# last30days-skill — Trend Research for Agents

Research skill that aggregates trending topics, repositories, and social signals
over the last 30 days from multiple sources.

## When to Use

- Before starting a new feature: check if an open-source solution already exists.
- Periodic market/tech landscape scans.
- Identifying emerging patterns in AI tooling, frameworks, or workflows.

## Workflow

1. **Define scope**: What domain or keyword cluster to scan (e.g. "AI agents", "memory systems", "RAG pipelines").
2. **Gather signals**:
   - GitHub Trending (use TrendShift.io or github.com/trending)
   - Hacker News (search.hn)
   - Reddit (r/MachineLearning, r/LocalLLaMA, r/AIAgents)
   - Twitter/X via web search
   - Product Hunt (last 30 days filter)
3. **Rank by relevance**: Score each finding against the current project's goals.
4. **Produce a report**: Markdown table with columns: Name, Source, Stars/Upvotes, Relevance (1-5), Summary, Action (ignore/evaluate/integrate).

## Output Format

```markdown
## Trend Report: <scope> — Last 30 Days

| # | Name | Source | Traction | Relevance | Summary | Action |
|---|------|--------|----------|-----------|---------|--------|
| 1 | ... | GitHub | 2.4k ⭐ | 5 | ... | integrate |
```

## Integration with Memory OS

Results should be saved as memory nodes via:
```bash
memory_os memory log --tags trend,research "<summary>"
```

This makes trend findings searchable by all agents in the swarm.

## Limitations

- This skill uses web search; results depend on search tool availability.
- No API keys required — all sources are publicly accessible.
- Refresh cadence: run weekly or before major planning sessions.
