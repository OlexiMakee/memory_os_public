# Project Context

Project: Governed Autonomous Intelligence Workspace.
Owner: Oleksii, news media analyst.
State: local-first Flask dashboard, AI chat in progress.
Runtime: macOS, Python 3.9, `venv_auto/`, SQLite local, Neon optional.

## Governance, Policy, & Ethical Guardrails

### Acceptable Use Boundaries
The workspace is built exclusively to support:
- News monitoring & editorial briefing
- Public narrative analysis & entity tracking
- Evidence-backed research & claim verification
- Crisis monitoring, OSINT investigation, and internal risk reporting

### Misuse & Prohibited Boundaries
The workspace explicitly prohibits and blocks the following workflows:
- Stalking, doxxing, or harvesting private credentials/data
- Covert influence operations or automated political persuasion
- Bot coordination or evasion of platform restrictions
- Unlawful surveillance or bypassing access controls

### Source Policy Tiers
All data sources ingested must belong to one of these governed tiers:
- **Tier A**: Official APIs or permitted programmatic feeds (allow with quotas)
- **Tier B**: Licensed, research, or partner feeds (allow with contract compliance)
- **Tier C**: User-provided owned sources, manual imports, and RSS (allow with ownership disclaimer)
- **Tier D**: Managed collection vendors with built-in governance (allow after vendor review)
- **Tier E**: Custom scrapers (disabled by default; requires explicit administrator whitelist)
- **Tier X**: Prohibited or high-risk collection sources (permanently blocked)

### Progressive Entitlement Modes
Feature access is scaffolded through entitlement flags, not ad hoc UI checks:
- `ready_workspace`: prebuilt editorial workspace and monitored source cards.
- `dense_workspace`: resizable widgets, saved layouts, dense analyst workflow.
- `linked_intelligence`: entity linking, timelines, cross-source evidence inspection.
- `operator_runtime`: source registry, connector runs, model routing, quotas, logs.
- `autonomous_watchers`: scheduled watchers, agent runs, anomaly queues, approval workflows.

Current scaffold: `app/state.py` exposes `ENTITLEMENT_FLAGS`, `DEFAULT_ENTITLEMENT_STATE`, and `get_entitlement_state()`.

### Basic UI Roles
UI visibility is role-tiered without changing backend authorization:
- `reader`: baseline Analysis workspace and read-only surfaces.
- `analyst`: reader plus widget palette, brief generation controls, assistant/model tooling.
- `admin`: analyst plus Administration, Operator Runtime, terminal, proposals, and collection/download actions.

Current scaffold: `/api/auth/status` returns backend `role` and `admin`; `static/js/auth.js` maps backend `user` to UI `reader`, preserves future `analyst`, and maps admin access to UI `admin`. Backend `require_admin` remains the enforcement layer.

## Start
```bash
python web_app.py
```
Default URL: `http://127.0.0.1:5001`. If occupied, app may use `5002`.

## Main Files
- `web_app.py`: legacy entrypoint.
- `app/`: Flask app factory, routes, services, state.
- `templates/index.html`: single dashboard page.
- `static/js/`: ES modules. Entry: `app.js`.
- `static/css/style.css`: themes, layout, chat drawer.
- `news_scraper/`: scraping, DB, sync clients.
- `data/youtube_news.db`: tracked local SQLite DB.
- `configs/schemas/`: DB/provider schemas.
- `agent_context/`: agent onboarding docs.
- `agent_proposals/`: archived proposals. Do not auto-implement.

## Architecture
- Flask app with Blueprints under `app/routes/`.
- Local SQLite is primary storage.
- Neon PostgreSQL is cloud sync/DR.
- Dashboard is server-rendered HTML plus JS modules.
- AI chat streams through backend agent endpoints.
- Provider rotation lives in `app/services/cloud_rotation.py`.

## Common Commands
```bash
venv_auto/bin/python -m compileall app news_scraper
python scripts/migrate_db.py
venv_auto/bin/python web_app.py
```
Use narrower compile/test scopes when possible.

## Multi-Agent Orchestration (Swarm Sync)
To prevent collisions and enable autonomous swarm operation, you MUST check the task queue before starting new work:
```bash
venv_auto/bin/python scripts/swarm_sync.py --agent="YOUR_NAME"
```
- Read the output. If you are assigned a task, proceed with it.
- Mark a task as done using `--complete="task_id.md"`.

## Key API
- `GET /`
- `GET /api/stats`
- `GET /api/channels`
- `GET /api/charts`
- `GET /api/videos`
- `POST /api/videos/{id}/scrape_details`
- `GET /api/auth/status`
- `POST /api/auth/session`
- `DELETE /api/auth/session`
- `POST /api/action/update`
- `POST /api/action/update_views`
- `POST /api/action/add_channel`
- `GET /api/action/status`
- `GET /api/admin/health`
- `GET /api/governance/policy`
- `GET /api/governance/readiness`
- `GET /api/sources`
- `POST /api/sources`
- `GET /api/source-connectors`
- `POST /api/sources/ingest`
- `GET /api/connector-runs`
- `GET /api/source-records`
- `GET /api/audit-events`
- `GET /api/evidence-links`
- `GET /api/source-credentials/status`
- `GET /api/widgets/registry`
- `GET /api/widgets/state`
- `PUT /api/widgets/state`
- `GET /api/terminal/stream`
- `POST /api/terminal/input`
- `POST /api/terminal/resize`
- `POST /api/action/shutdown`
- `GET /api/agent/models`
- `POST /api/agent/chat/stream`
- `POST /api/chat/feedback`
- `POST /api/chat/report-quota`
- `GET /api/proposals`
- `POST /api/proposals/submit`
- `POST /api/proposals/status`
- `GET /api/analytics/anomalies`
- `GET /api/analytics/data-methods`
- `POST /api/analytics/data-methods/review`


## DB
SQLite path: `data/youtube_news.db`.

Core tables:
- `channels`
- `videos`

Important video fields:
- `video_id`
- `channel_id`
- `title`
- `published_at`
- `view_count`
- `like_count`
- `comment_count`
- `full_description`
- `views_update` as JSON text

## Env
Never print values.
- `YOUTUBE_API_KEY`
- `DATABASE_URL`

> **Memory OS Audit Checkpoint:** 2026-06-02 memory_os micro-steps complete; verify `scripts/memory_os.py audit` before Gemini giant agent activation.
- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `OPENROUTER_API_KEY`
- `OLLAMA_API_KEY`
- `KAGGLE_USERNAME`
- `KAGGLE_KEY`

## Known Risks
- `web_app.py` can bootstrap dependencies; avoid unnecessary restarts.
- `/api/charts` is heavy.
- `views_update` is JSON text, not normalized.
- Some UI state is stored in browser `localStorage`.
- Browser runtime may be unavailable in Codex; report static-only UI checks.
- Large temp uploads under `.tmp.*` can overheat indexing/processes. Keep ignored.
- Local LLMs are forbidden: no `OLLAMA_HOST`, no `localhost:11434`, no local Ollama model IDs.
- DB migrations must go through `scripts/migrate_db.py`; default dry-run, explicit `--apply`, backup first.

## Current UI Rules
- Top filter/stat area should stay sticky.
- Chart text that users copy should exist in DOM, not canvas only.
- Top 100/list items should keep full title on hover and reuse existing detail modal.
- AI chat open/close controls are separate from summarize action.
