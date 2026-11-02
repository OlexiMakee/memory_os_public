#!/usr/bin/env python3
"""Portable Memory OS control CLI for project-local operations."""

from __future__ import annotations

import argparse
from memory_os.toolkit.agent_registry import KNOWN_AGENTS
import shutil
import sys
import os
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc

from memory_os.cli_groups.agent_cmds import cmd_task, cmd_plan, cmd_dispatch, cmd_comm, cmd_handoff, cmd_agent_registry, cmd_agent_manager, cmd_agent_run, cmd_swarm_send, cmd_swarm_watch
from memory_os.cli_groups.memory_cmds import cmd_snapshot, cmd_ingest, cmd_change_size, cmd_compact, cmd_sync, cmd_compress, cmd_link_infer, cmd_prune, cmd_transition, cmd_graph_map, cmd_query, cmd_backlinks, cmd_memory_browse, cmd_memory_write, cmd_memory_log, cmd_memory_show, cmd_memory_revert, cmd_memory_normalize_timecodes, cmd_memory_health, cmd_memory_curate, cmd_memory_dedup_candidates, cmd_memory_merge_preview, cmd_memory_merge_apply, cmd_unlinked, cmd_stats, cmd_rag, cmd_ingest_transcript, cmd_search, cmd_db_optimize, cmd_export_obsidian
from memory_os.cli_groups.system_cmds import cmd_init, cmd_integrate, cmd_audit, cmd_switch_space, cmd_check_updates, cmd_validate, cmd_daemon, cmd_ls, cmd_install, cmd_workspace, cmd_zellij, cmd_run_daemon_blocking, cmd_monitor, cmd_ui, cmd_resources, cmd_storage, cmd_telemetry, cmd_git_commit_safe, cmd_release_check, _print_workspace_runtime_doctor, cmd_doctor, cmd_killall, cmd_undo
from memory_os.cli_groups.llm_cmds import (cmd_models, cmd_quantize, cmd_eval, cmd_route, cmd_budget, cmd_adapters_audit, cmd_mcp, cmd_run, cmd_provider, cmd_prompt, cmd_compile_prompt)
from memory_os.cli_groups.persona_cmds import (cmd_idea, cmd_persona_sync, cmd_persona)
from memory_os.cli_groups.spec_cmds import (cmd_workflows, cmd_spec, cmd_contract, cmd_context, cmd_evidence, cmd_security_scan, cmd_review_pack, cmd_codebase, cmd_triage, cmd_review, cmd_approve)
from memory_os.cli_groups.lora_cmds import (cmd_lora_dataset_build, cmd_lora_script_render, cmd_lora_registry, cmd_lora_list)
from memory_os.cli_groups.os_cmds import (cmd_analyze_os, cmd_linux, cmd_xfce, cmd_giant_scan)
from memory_os.cli_groups.telegram_cmds import cmd_telegram_daemon, cmd_telegram_daemon_control
from memory_os.cli_groups.tmux_cmds import (cmd_tmux)
from memory_os.cli_groups.sync_cmds import (cmd_pipeline, cmd_linear_sync, cmd_notion_sync, cmd_gdrive_sync)
from memory_os.cli_groups.misc_cmds import (cmd_observe, cmd_analytics, cmd_export_skills, cmd_skills)


# Load .env from the current working directory (the user's project root)
_env_file = Path.cwd() / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip())

from memory_os import MemoryOSConfig

DEFAULT_WORKFLOWS = """# Workflows

Use two explicit workstreams:
- `product`: customer-facing product work.
- `memory_os`: internal shorthand for agent workflow, telemetry, repo analysis, and self-improvement tools.

Naming guard: `memory_os` is the internal command/workflow alias.

Step scale: 1 nano, 2 micro, 3 tiny, 4 little, 5 pretty little, 6 light mid,
7 mid, 8 high mid, 9 mid high, 10 big, 11 large, 12 giant.
"""

DEFAULT_AGENTS_BLOCK = """\n## Memory OS Integration

- Read `agent_context/WORKFLOWS.md` before choosing task scope.
- Route work through `product` or `memory_os`.
- Use the 12-step scale from `nano` to `giant`.
- For non-trivial feature work, run `python -m memory_os spec init "<title>"` and keep spec/plan/tasks traceable.
- Run `python -m memory_os audit` before broad Memory OS changes.
"""

DEFAULT_WORKFLOW_TOMLS = {
    "chat.nano.toml": """id = "chat.nano"
step_min = 0
step_max = 2
level_min = 1
level_max = 18
model_policy = "cheap_free"
tools = ["search_memory"]
verification = ["schema_check"]

[memory_policy]
max_cards = 3
max_tokens = 1200

[escalation]
if_uncertainty_above = 0.6
escalate_to = "chat.standard"
""",
    "code.small.toml": """id = "code.small"
step_min = 3
step_max = 8
level_min = 26
level_max = 64
model_policy = "codex"
tools = ["search_memory", "validate_memory"]
verification = ["test_run_required"]

[memory_policy]
max_cards = 10
max_tokens = 4000

[escalation]
if_risk_above = 0.5
escalate_to = "code.standard"
""",
    "architecture.giant.toml": """id = "architecture.giant"
step_min = 9
step_max = 13
level_min = 65
level_max = 100
model_policy = "large_reasoning"
tools = ["repo_index", "symbol_search", "test_runner", "adr_writer"]
verification = ["dry_run_required", "user_approval_required"]

[memory_policy]
root_files = ["AGENTS.md", "INDEX.md", "README.md"]
graph_depth = 3
require_evidence = true

[output]
format = "adr_proposal"
""",
}














































































































































try:
    from memory_os.ide_grant_private import cmd_ide_grant
except ImportError:
    cmd_ide_grant = None

























































class _CleanHelpFormatter(argparse.HelpFormatter):
    """Hides subcommands registered with help=argparse.SUPPRESS."""
    def _format_action(self, action):
        if action.help == argparse.SUPPRESS:
            return ""
        result = super()._format_action(action)
        # Also strip SUPPRESS entries from subparsers choice list
        if hasattr(action, "_choices_actions"):
            action._choices_actions = [
                a for a in action._choices_actions if a.help != argparse.SUPPRESS
            ]
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Memory OS project-local CLI.",
        formatter_class=_CleanHelpFormatter,
    )
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--config", help="Path to memory_os.config.json file")
    parser.add_argument("--space", type=str, default="default", help="Memory space to operate on (e.g. default, user_persona)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create missing Memory OS control files.")
    init_parser.set_defaults(func=cmd_init)

    integrate_parser = subparsers.add_parser("integrate", help="Add minimal Memory OS agent instructions.")
    integrate_parser.add_argument(
        "--install-git-hooks",
        action="store_true",
        help=(
            "Install pre-commit/post-commit Git hooks. The memory_os CLI is resolved at runtime "
            "($VIRTUAL_ENV, venv_auto, .venv, venv, env, PATH). Gate: release-check in the memory_os "
            "package repo; validate + security scan in consumer projects."
        ),
    )
    integrate_parser.set_defaults(func=cmd_integrate)

    audit_parser = subparsers.add_parser("audit", help="Audit Memory OS control-plane state.")
    audit_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    audit_parser.set_defaults(func=cmd_audit)

    validate_parser = subparsers.add_parser("validate", help="Validate task capsules and lifecycle JSONL.")
    validate_parser.set_defaults(func=cmd_validate)

    snapshot_parser = subparsers.add_parser("snapshot", help="Build compact memory snapshot for this repo.")
    snapshot_parser.add_argument("--write", action="store_true", help="Write agent_context/memory_snapshot.json")
    snapshot_parser.set_defaults(func=cmd_snapshot)

    quantize_parser = subparsers.add_parser("quantize", help="Quantize a task into the 12-step Memory OS scale.")
    quantize_parser.add_argument("--task", required=True, help="Task description")
    quantize_parser.add_argument("--risk", type=float, default=0.0)
    quantize_parser.add_argument("--volume", type=float, default=0.0)
    quantize_parser.add_argument("--uncertainty", type=float, default=0.0)
    quantize_parser.add_argument("--format", choices={"json", "text"}, default="text")
    quantize_parser.set_defaults(func=cmd_quantize)

    models_parser = subparsers.add_parser("models", help="Manage and recommend local models based on system hardware.")
    models_subparsers = models_parser.add_subparsers(dest="models_action", required=True)
    models_recommend_parser = models_subparsers.add_parser("recommend", help="Recommend local models that fit host hardware.")
    models_recommend_parser.add_argument("--format", choices={"json", "text"}, default="text")
    models_recommend_parser.set_defaults(func=cmd_models)

    workflows_parser = subparsers.add_parser("workflows", help="Validate workflow TOML specs and build a manifest.")
    workflows_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    workflows_parser.add_argument("--write-manifest", action="store_true")
    workflows_parser.add_argument("--manifest-path", default="memory/workflow_manifest.json")
    workflows_parser.set_defaults(func=cmd_workflows)

    spec_parser = subparsers.add_parser(
        "spec",
        help="Create and validate spec-driven development artifacts.",
    )
    spec_subparsers = spec_parser.add_subparsers(dest="spec_action", required=True)

    spec_init_parser = spec_subparsers.add_parser("init", help="Create specs/<id>/ files.")
    spec_init_parser.add_argument("title", help="Feature or change title.")
    spec_init_parser.add_argument("--description", default="", help="Short goal statement.")
    spec_init_parser.add_argument("--id", help="Explicit feature id, e.g. 001-retrieval-router.")
    spec_init_parser.add_argument("--force", action="store_true", help="Overwrite existing spec files.")
    spec_init_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_init_parser.set_defaults(func=cmd_spec)

    spec_constitution_parser = spec_subparsers.add_parser(
        "constitution",
        help="Create agent_context/CONSTITUTION.md if missing.",
    )
    spec_constitution_parser.add_argument("--force", action="store_true", help="Overwrite existing constitution.")
    spec_constitution_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_constitution_parser.set_defaults(func=cmd_spec)

    spec_list_parser = spec_subparsers.add_parser("list", help="List local specs.")
    spec_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_list_parser.set_defaults(func=cmd_spec)

    spec_analyze_parser = spec_subparsers.add_parser("analyze", help="Validate spec quality gates.")
    spec_analyze_parser.add_argument("feature", nargs="?", help="Feature id or unique prefix. Defaults to latest.")
    spec_analyze_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    spec_analyze_parser.set_defaults(func=cmd_spec)

    spec_sync_parser = spec_subparsers.add_parser("sync", help="Scan local spec files and sync requirements to the memory graph.")
    spec_sync_parser.add_argument("--format", choices={"json", "text"}, default="text")
    spec_sync_parser.set_defaults(func=cmd_spec)

    contract_parser = subparsers.add_parser(
        "contract",
        help="Derive a machine-readable contract from existing spec/plan artifacts.",
    )
    contract_subparsers = contract_parser.add_subparsers(dest="contract_action", required=True)

    contract_build_parser = contract_subparsers.add_parser("build", help="Build contract.json/contract.md for a spec.")
    contract_build_parser.add_argument("feature", nargs="?", help="Feature id or unique prefix. Defaults to latest.")
    contract_build_parser.add_argument("--risk-class", dest="risk_class", default=None, help="Override the inferred risk class (e.g. low, moderate, migration-risk).")
    contract_build_parser.add_argument("--force", action="store_true", help="Overwrite an existing contract.")
    contract_build_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    contract_build_parser.set_defaults(func=cmd_contract)

    context_parser = subparsers.add_parser(
        "context",
        help="Build a targeted, reproducible context pack instead of dumping the repo into the model.",
    )
    context_subparsers = context_parser.add_subparsers(dest="context_action", required=True)

    context_build_parser = context_subparsers.add_parser("build", help="Build a context pack from a task description and/or a contract file.")
    context_build_parser.add_argument("--task", default="", help="Task description used for relevance scoring.")
    context_build_parser.add_argument("--contract", default=None, help="Path to a contract.json/contract.md to seed task_summary/constraints/verification_plan.")
    context_build_parser.add_argument("--path", action="append", default=[], help="Repeatable root-relative file or directory to scan. Defaults to the project root.")
    context_build_parser.add_argument("--include-private", action="store_true", help="Opt in to files excluded by private/export-ignore policy.")
    context_build_parser.add_argument("--dry-run", action="store_true", help="Print the pack without writing it to agent_context/context_packs/.")
    context_build_parser.add_argument("--format", choices={"markdown", "json"}, default="markdown")
    context_build_parser.set_defaults(func=cmd_context)

    evidence_parser = subparsers.add_parser(
        "evidence",
        help="Build a verification evidence bundle: commands run, exit codes, changed files, gaps.",
    )
    evidence_subparsers = evidence_parser.add_subparsers(dest="evidence_action", required=True)

    evidence_init_parser = evidence_subparsers.add_parser("init", help="Create a new evidence bundle for a task.")
    evidence_init_parser.add_argument("--task", required=True, help="Task id.")
    evidence_init_parser.add_argument("--risk-class", dest="risk_class", default=None)
    evidence_init_parser.add_argument("--force", action="store_true")
    evidence_init_parser.add_argument("--dry-run", action="store_true")
    evidence_init_parser.add_argument("--format", choices={"json", "text"}, default="text")
    evidence_init_parser.set_defaults(func=cmd_evidence)

    evidence_add_command_parser = evidence_subparsers.add_parser("add-command", help="Run a command and record it (exit code + bounded, redacted output) in the bundle.")
    evidence_add_command_parser.add_argument("--task", required=True, help="Task id.")
    evidence_add_command_parser.add_argument("--dry-run", action="store_true", help="Run the command but do not save it to the bundle.")
    evidence_add_command_parser.add_argument("--format", choices={"json", "text"}, default="text")
    evidence_add_command_parser.add_argument("command", nargs=argparse.REMAINDER, help="-- <command and args to run>")
    evidence_add_command_parser.set_defaults(func=cmd_evidence)

    evidence_summarize_parser = evidence_subparsers.add_parser("summarize", help="Refresh changed files, append notes, and render a summary.")
    evidence_summarize_parser.add_argument("--task", required=True, help="Task id.")
    evidence_summarize_parser.add_argument("--manual-check", action="append", default=[], help="Repeatable: append a manual check note.")
    evidence_summarize_parser.add_argument("--known-gap", action="append", default=[], help="Repeatable: append a known gap.")
    evidence_summarize_parser.add_argument("--reviewer-note", action="append", default=[], help="Repeatable: append a reviewer note.")
    evidence_summarize_parser.add_argument("--dry-run", action="store_true")
    evidence_summarize_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    evidence_summarize_parser.set_defaults(func=cmd_evidence)

    evidence_verify_parser = evidence_subparsers.add_parser("verify", help="Exit non-zero unless every recorded command passed and risk_class is set.")
    evidence_verify_parser.add_argument("--task", required=True, help="Task id.")
    evidence_verify_parser.add_argument("--format", choices={"json", "text"}, default="text")
    evidence_verify_parser.set_defaults(func=cmd_evidence)

    review_pack_parser = subparsers.add_parser(
        "review-pack",
        help="Assemble contract + context pack + evidence into one reviewer-facing document.",
    )
    review_pack_parser.add_argument("--task", required=True, help="Task id (same id used for 'evidence init --task').")
    review_pack_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    review_pack_parser.set_defaults(func=cmd_review_pack)

    change_size_parser = subparsers.add_parser(
        "change-size",
        help="Advisory small-batch warnings for the current uncommitted change set.",
    )
    change_size_parser.add_argument("--format", choices={"json", "text"}, default="text")
    change_size_parser.set_defaults(func=cmd_change_size)

    security_parser = subparsers.add_parser(
        "security",
        help="Offline secret and prompt-injection scan over local-first memory stores.",
    )
    security_subparsers = security_parser.add_subparsers(dest="security_action", required=True)
    security_scan_parser = security_subparsers.add_parser("scan", help="Scan memory/evidence/context-pack stores for secrets and injection markers.")
    security_scan_parser.add_argument("--profile", choices={"default", "private-docs", "context-artifacts", "docs", "all"}, default="default")
    security_scan_parser.add_argument("--format", choices={"json", "text"}, default="text")
    security_scan_parser.set_defaults(func=cmd_security_scan)

    prompt_parser = subparsers.add_parser(
        "prompt",
        help="List, show, render, or verify versioned prompt templates (no LLM call).",
    )
    prompt_subparsers = prompt_parser.add_subparsers(dest="prompt_action", required=True)

    prompt_list_parser = prompt_subparsers.add_parser("list", help="List all prompts with id/version/hash.")
    prompt_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_list_parser.set_defaults(func=cmd_prompt)

    prompt_show_parser = prompt_subparsers.add_parser("show", help="Show one prompt's metadata and body.")
    prompt_show_parser.add_argument("id", help="Prompt id (matches its filename stem).")
    prompt_show_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_show_parser.set_defaults(func=cmd_prompt)

    prompt_render_parser = prompt_subparsers.add_parser("render", help="Render a prompt body with {{var}} substitutions.")
    prompt_render_parser.add_argument("id", help="Prompt id.")
    prompt_render_parser.add_argument("--input", action="append", help="key=value, repeatable.")
    prompt_render_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_render_parser.set_defaults(func=cmd_prompt)

    prompt_verify_parser = prompt_subparsers.add_parser("verify", help="Check every prompt file has required frontmatter and a matching id.")
    prompt_verify_parser.add_argument("--format", choices={"json", "text"}, default="text")
    prompt_verify_parser.set_defaults(func=cmd_prompt)

    idea_parser = subparsers.add_parser(
        "idea",
        help="Expand a rough idea into a discovery-brief prompt (rendering only, no LLM call).",
    )
    idea_subparsers = idea_parser.add_subparsers(dest="idea_action", required=True)
    idea_expand_parser = idea_subparsers.add_parser("expand", help="Render the idea_expand prompt for a raw idea.")
    idea_expand_parser.add_argument("--text", required=True, help="The raw idea text.")
    idea_expand_parser.add_argument("--dry-run", action="store_true", help="Accepted for forward-compat; rendering is always dry (no LLM call exists yet).")
    idea_expand_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    idea_expand_parser.set_defaults(func=cmd_idea)

    lora_parser = subparsers.add_parser(
        "lora",
        help="Build datasets and render training scripts for local LoRA skill adapters. "
             "Offline only — actual training runs on separate GPU hardware, not here.",
    )
    lora_subparsers = lora_parser.add_subparsers(dest="lora_action", required=True)

    lora_dataset_parser = lora_subparsers.add_parser("dataset", help="Dataset operations.")
    lora_dataset_subparsers = lora_dataset_parser.add_subparsers(dest="lora_dataset_action", required=True)
    lora_dataset_build_parser = lora_dataset_subparsers.add_parser(
        "build", help="Build a TRL-ready JSONL dataset from task capsules and/or local documents."
    )
    lora_dataset_build_parser.add_argument("--adapter", required=True, help="Adapter name, e.g. 'memory', 'docs', 'terminal'.")
    lora_dataset_build_parser.add_argument(
        "--source", choices={"capsules", "sqlite", "docs", "action_router", "telegram", "responder"}, action="append", default=None,
        help="Repeatable. 'capsules' = agent_context/task_capsules.jsonl, "
             "'sqlite' = verified nodes already in memory_os.db (no new datastore), "
             "'docs' = local files via --doc-root/--doc-glob, "
             "'telegram' = real Telegram action-router conversations. Default: capsules.",
    )
    lora_dataset_build_parser.add_argument("--doc-root", default=None, help="Root directory to glob for --source docs/both (default: project root).")
    lora_dataset_build_parser.add_argument("--doc-glob", action="append", default=None, help="Glob pattern relative to --doc-root (repeatable). Default: '**/*.md'.")
    lora_dataset_build_parser.add_argument("--instruction", default="Summarize this document and extract any rules/facts worth remembering.")
    lora_dataset_build_parser.add_argument("--system-prompt", default="You are a local Memory OS assistant.")
    lora_dataset_build_parser.add_argument("--out", required=True, help="Output JSONL path, relative to project root.")
    lora_dataset_build_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_dataset_build_parser.set_defaults(func=cmd_lora_dataset_build)

    lora_script_parser = lora_subparsers.add_parser("script", help="Training script operations.")
    lora_script_subparsers = lora_script_parser.add_subparsers(dest="lora_script_action", required=True)
    lora_script_render_parser = lora_script_subparsers.add_parser(
        "render", help="Render an Unsloth+TRL+PEFT training script for one adapter and register it."
    )
    lora_script_render_parser.add_argument("--adapter", required=True)
    lora_script_render_parser.add_argument("--base-model", required=True, help="e.g. 'Qwen/Qwen3-8B'.")
    lora_script_render_parser.add_argument("--dataset", required=True, help="Path to the JSONL built by 'lora dataset build'.")
    lora_script_render_parser.add_argument("--output-dir", required=True, help="Where the training run (and final adapter) should be written, on the GPU machine.")
    lora_script_render_parser.add_argument("--script-out", required=True, help="Where to write the rendered .py script, relative to project root.")
    lora_script_render_parser.add_argument("--rank", type=int, default=16)
    lora_script_render_parser.add_argument("--alpha", type=int, default=32)
    lora_script_render_parser.add_argument("--epochs", type=int, default=3)
    lora_script_render_parser.add_argument(
        "--method", choices={"sft", "dpo", "grpo"}, default="sft",
        help="'sft' (default) teaches output format/syntax. 'dpo' ranks chosen-vs-rejected "
             "responses -- run as a second stage after an 'sft' adapter already trained. "
             "'grpo' optimizes against a reward function the rendered script stubs as a TODO.",
    )
    lora_script_render_parser.add_argument("--description", default="")
    lora_script_render_parser.add_argument(
        "--role", choices={"action", "responder"}, default="action",
        help="'action' feeds an agent_brain ActionBrain (terse JSON-only); 'responder' feeds a Responder (natural language).",
    )
    lora_script_render_parser.add_argument(
        "--capability", action="append", default=None,
        help="Repeatable. Declarative task tag this adapter covers, e.g. 'sql', 'uk_slang'. Not enforced anywhere yet.",
    )
    lora_script_render_parser.add_argument(
        "--compatible-with", action="append", default=None,
        help="Repeatable. Names of other adapters this one is known to combine safely with. Declarative only.",
    )
    lora_script_render_parser.add_argument(
        "--incompatible-with", action="append", default=None,
        help="Repeatable. Names of other adapters known to conflict with this one. Declarative only.",
    )
    lora_script_render_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_script_render_parser.set_defaults(func=cmd_lora_script_render)

    lora_list_parser = lora_subparsers.add_parser("list", help="List registered LoRA adapters (current/promoted version per adapter).")
    lora_list_parser.add_argument("--capability", default=None, help="Filter to adapters declaring this capability tag.")
    lora_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_list_parser.set_defaults(func=cmd_lora_list)

    lora_registry_parser = lora_subparsers.add_parser("registry", help="Inspect and promote/reject specific adapter versions.")
    lora_registry_subparsers = lora_registry_parser.add_subparsers(dest="lora_registry_action", required=True)

    lora_registry_versions_parser = lora_registry_subparsers.add_parser("versions", help="List every registered version of one adapter.")
    lora_registry_versions_parser.add_argument("--adapter", required=True)
    lora_registry_versions_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_registry_versions_parser.set_defaults(func=cmd_lora_registry)

    lora_registry_promote_parser = lora_registry_subparsers.add_parser(
        "promote", help="Make a candidate version the current one for an adapter — do this only after eval confirms it's better."
    )
    lora_registry_promote_parser.add_argument("--adapter", required=True)
    lora_registry_promote_parser.add_argument("--version", required=True, help="e.g. v002 (from 'lora script render' or 'lora registry versions').")
    lora_registry_promote_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_registry_promote_parser.set_defaults(func=cmd_lora_registry)

    lora_registry_reject_parser = lora_registry_subparsers.add_parser("reject", help="Mark a candidate version as rejected — eval said it's worse.")
    lora_registry_reject_parser.add_argument("--adapter", required=True)
    lora_registry_reject_parser.add_argument("--version", required=True)
    lora_registry_reject_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_registry_reject_parser.set_defaults(func=cmd_lora_registry)

    lora_registry_metrics_parser = lora_registry_subparsers.add_parser(
        "metrics", help="Attach post-eval metrics (accuracy, json_validity, latency_ms, ...) to a specific version."
    )
    lora_registry_metrics_parser.add_argument("--adapter", required=True)
    lora_registry_metrics_parser.add_argument("--version", required=True)
    lora_registry_metrics_parser.add_argument("--set", action="append", help="key=value, repeatable.")
    lora_registry_metrics_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_registry_metrics_parser.set_defaults(func=cmd_lora_registry)

    lora_registry_compatible_parser = lora_registry_subparsers.add_parser(
        "compatible", help="Declarative check: do two adapters' declared compatible_with/incompatible_with lists allow combining them?"
    )
    lora_registry_compatible_parser.add_argument("--adapter-a", required=True, dest="adapter_a")
    lora_registry_compatible_parser.add_argument("--adapter-b", required=True, dest="adapter_b")
    lora_registry_compatible_parser.add_argument("--format", choices={"json", "text"}, default="text")
    lora_registry_compatible_parser.set_defaults(func=cmd_lora_registry)

    agent_parser = subparsers.add_parser(
        "agent",
        help="Run the agent_brain Orchestrator (ActionBrain -> validated dispatch -> real executor). See docs/encyclopedia/agent_brain.md.",
    )
    agent_subparsers = agent_parser.add_subparsers(dest="agent_action", required=True)
    agent_run_parser = agent_subparsers.add_parser(
        "run", help="Propose one action for a task via LocalLLMActionBrain and execute it against this project's real memory graph."
    )
    agent_run_parser.add_argument("--task", required=True, help="Free-text task description.")
    agent_run_parser.add_argument("--provider", default=None, help="Optional provider override (ollama, gemini, groq, openrouter, openai).")
    agent_run_parser.add_argument("--model", default=None, help="Optional model override — point this at a trained action-LoRA's Ollama tag once one exists.")
    agent_run_parser.add_argument("--format", choices={"json", "text"}, default="text")
    agent_run_parser.set_defaults(func=cmd_agent_run)

    route_parser = subparsers.add_parser("route", help="Route a task to a provider/model via LLMRouter (no network call).")
    route_parser.add_argument("--task", required=True, help="Free-text task description.")
    route_parser.add_argument("--format", choices={"json", "text"}, default="json")
    route_parser.set_defaults(func=cmd_route)

    budget_parser = subparsers.add_parser("budget", help="Token budget status.")
    budget_subparsers = budget_parser.add_subparsers(dest="budget_action", required=True)
    budget_status_parser = budget_subparsers.add_parser("status", help="Show daily token budget status.")
    budget_status_parser.add_argument("--format", choices={"json", "text"}, default="text")
    budget_status_parser.set_defaults(func=cmd_budget)

    provider_parser = subparsers.add_parser("provider", help="List or offline-test known model providers/adapters.")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_action", required=True)
    provider_list_parser = provider_subparsers.add_parser("list", help="List known providers and adapter/config status.")
    provider_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    provider_list_parser.set_defaults(func=cmd_provider)
    provider_test_parser = provider_subparsers.add_parser("test", help="Offline-only readiness check for one provider (no network call).")
    provider_test_parser.add_argument("name", help="Provider name (see 'provider list').")
    provider_test_parser.add_argument("--format", choices={"json", "text"}, default="text")
    provider_test_parser.set_defaults(func=cmd_provider)

    adapters_parser = subparsers.add_parser("adapters", help="Audit optional adapter availability (offline, no network).")
    adapters_subparsers = adapters_parser.add_subparsers(dest="adapters_action", required=True)
    adapters_audit_parser = adapters_subparsers.add_parser("audit", help="Report install status for every optional adapter.")
    adapters_audit_parser.add_argument("--format", choices={"json", "text"}, default="text")
    adapters_audit_parser.set_defaults(func=cmd_adapters_audit)

    ingest_file_parser = subparsers.add_parser(
        "ingest",
        help="Convert an external document to Markdown via the optional MarkItDown adapter.",
    )
    ingest_subparsers = ingest_file_parser.add_subparsers(dest="ingest_action", required=True)
    ingest_file_sub = ingest_subparsers.add_parser("file", help="Convert one local file (untrusted; no network fetch; no script execution).")
    ingest_file_sub.add_argument("path", help="Local file path.")
    ingest_file_sub.add_argument("--allow-outside-root", action="store_true", help="Explicitly permit reading a file outside the Memory OS workspace.")
    ingest_file_sub.add_argument("--include-private", action="store_true", help="Explicitly permit files hidden by private/export-ignore policy.")
    ingest_file_sub.add_argument("--write", action="store_true", help="Reserved for future persistence; conversion itself never writes to disk.")
    ingest_file_sub.add_argument("--format", choices={"json", "text"}, default="text")
    ingest_file_sub.set_defaults(func=cmd_ingest)

    observe_parser = subparsers.add_parser("observe", help="OpenTelemetry-compatible export status/dry-run over bounded local telemetry.")
    observe_subparsers = observe_parser.add_subparsers(dest="observe_action", required=True)
    observe_status_parser = observe_subparsers.add_parser("status", help="Report OTel SDK availability (offline).")
    observe_status_parser.add_argument("--format", choices={"json", "text"}, default="text")
    observe_status_parser.set_defaults(func=cmd_observe)
    observe_export_parser = observe_subparsers.add_parser("export", help="Export bounded telemetry to OTel spans/metrics (dry-run by default).")
    observe_export_parser.add_argument("--target", choices={"otel"}, default="otel")
    observe_export_parser.add_argument("--dry-run", action="store_true", default=True, help="Default; pass --write to actually attempt an OTel export.")
    observe_export_parser.add_argument("--write", dest="dry_run", action="store_false", help="Attempt a real OTel export (requires the optional SDK).")
    observe_export_parser.add_argument("--sample-rate", dest="sample_rate", type=float, default=1.0)
    observe_export_parser.add_argument("--format", choices={"json", "text"}, default="text")
    observe_export_parser.set_defaults(func=cmd_observe)

    analytics_parser = subparsers.add_parser("analytics", help="Local analytics reports over evals/telemetry/evidence via the optional DuckDB adapter.")
    analytics_subparsers = analytics_parser.add_subparsers(dest="analytics_action", required=True)
    analytics_report_parser = analytics_subparsers.add_parser("report", help="Aggregate one topic.")
    analytics_report_parser.add_argument("--topic", choices={"evals", "telemetry", "evidence"}, required=True)
    analytics_report_parser.add_argument("--format", choices={"json", "text"}, default="text")
    analytics_report_parser.set_defaults(func=cmd_analytics)
    analytics_export_parser = analytics_subparsers.add_parser("export", help="Export an analytics inventory (dry-run by default).")
    analytics_export_parser.add_argument("--export-format", dest="export_format", choices={"json", "parquet"}, default="json")
    analytics_export_parser.add_argument("--dry-run", action="store_true", default=True, help="Default; pass --write to actually write the export file.")
    analytics_export_parser.add_argument("--write", dest="dry_run", action="store_false", help="Actually write the export file (requires the optional duckdb package).")
    analytics_export_parser.add_argument("--format", choices={"json", "text"}, default="text")
    analytics_export_parser.set_defaults(func=cmd_analytics)

    mcp_parser = subparsers.add_parser("mcp", help="MCP capability manifest/audit/serve (optional, least-privilege by default).")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_action", required=True)
    mcp_manifest_parser = mcp_subparsers.add_parser("manifest", help="Show the allowed/denied MCP tool manifest.")
    mcp_manifest_parser.set_defaults(func=cmd_mcp)
    mcp_audit_parser = mcp_subparsers.add_parser("audit", help="Report MCP SDK availability and tool counts (offline).")
    mcp_audit_parser.set_defaults(func=cmd_mcp)
    mcp_serve_parser = mcp_subparsers.add_parser("serve", help="Dry-run by default; --write attempts a real server (not implemented in this stage).")
    mcp_serve_parser.add_argument("--write", action="store_true", help="Attempt a real MCP server instead of a dry-run description.")
    mcp_serve_parser.set_defaults(func=cmd_mcp)
    for p in (mcp_manifest_parser, mcp_audit_parser, mcp_serve_parser):
        p.add_argument("--format", choices={"json", "text"}, default="json")

    run_parser = subparsers.add_parser("run", help="Lightweight native run/checkpoint records (no workflow engine; see Stage 14).")
    run_subparsers = run_parser.add_subparsers(dest="run_action", required=True)
    run_start_parser = run_subparsers.add_parser("start", help="Start a new run record.")
    run_start_parser.add_argument("--workflow", required=True, help="Workflow name, e.g. idea-to-spec.")
    run_start_parser.add_argument("--inputs", help="JSON object string of inputs.")
    run_start_parser.set_defaults(func=cmd_run)
    run_status_parser = run_subparsers.add_parser("status", help="Show one run's current record.")
    run_status_parser.add_argument("run_id")
    run_status_parser.set_defaults(func=cmd_run)
    run_resume_parser = run_subparsers.add_parser("resume", help="Return the persisted state for a run (no re-execution).")
    run_resume_parser.add_argument("run_id")
    run_resume_parser.set_defaults(func=cmd_run)
    run_complete_parser = run_subparsers.add_parser("complete", help="Mark a run completed with outputs.")
    run_complete_parser.add_argument("run_id")
    run_complete_parser.add_argument("--outputs", help="JSON object string of outputs.")
    run_complete_parser.set_defaults(func=cmd_run)
    run_abort_parser = run_subparsers.add_parser("abort", help="Mark a run aborted.")
    run_abort_parser.add_argument("run_id")
    run_abort_parser.set_defaults(func=cmd_run)
    run_list_parser = run_subparsers.add_parser("list", help="List all run records.")
    run_list_parser.set_defaults(func=cmd_run)
    for p in (run_start_parser, run_status_parser, run_resume_parser, run_complete_parser, run_abort_parser, run_list_parser):
        p.add_argument("--format", choices={"json", "text"}, default="text")

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run local-deterministic and optional LLM-judge eval suites for nondeterministic surfaces.",
    )
    eval_subparsers = eval_parser.add_subparsers(dest="eval_action", required=True)

    eval_list_parser = eval_subparsers.add_parser("list", help="List available eval suites.")
    eval_list_parser.add_argument("--format", choices={"json", "text"}, default="text")
    eval_list_parser.set_defaults(func=cmd_eval)

    eval_run_parser = eval_subparsers.add_parser("run", help="Run one eval suite by name.")
    eval_run_parser.add_argument("suite", help="Suite name (see 'eval list').")
    eval_run_parser.add_argument("--format", choices={"json", "text"}, default="text")
    eval_run_parser.set_defaults(func=cmd_eval)

    eval_compare_parser = eval_subparsers.add_parser("compare", help="Diff two saved 'eval run --format json' result files.")
    eval_compare_parser.add_argument("baseline", help="Path to a saved baseline result JSON file.")
    eval_compare_parser.add_argument("candidate", help="Path to a saved candidate result JSON file.")
    eval_compare_parser.add_argument("--format", choices={"json", "text"}, default="text")
    eval_compare_parser.set_defaults(func=cmd_eval)

    eval_export_parser = eval_subparsers.add_parser("export", help="Export a suite to a best-effort Inspect AI / promptfoo config shape.")
    eval_export_parser.add_argument("suite", help="Suite name (see 'eval list').")
    eval_export_parser.add_argument("--target", choices={"inspect", "promptfoo"}, required=True)
    eval_export_parser.set_defaults(func=cmd_eval)

    compact_parser = subparsers.add_parser(
        "compact",
        help="Parse task capsules to extract new memory nodes and edges via LLM.",
    )
    compact_parser.add_argument("--provider", help="Optional provider override (ollama, gemini, groq, openrouter, openai). Default: local Ollama first, then free cloud tiers.")
    compact_parser.add_argument("--model", help="Optional model override")
    compact_parser.set_defaults(func=cmd_compact)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync JSONL memory nodes to SQLite FTS5 graph database.",
    )
    sync_parser.set_defaults(func=cmd_sync)

    export_skills_parser = subparsers.add_parser(
        "export-skills",
        help="Export Memory OS write-skills for Claude Code to .claude/skills/ directory.",
    )
    export_skills_parser.set_defaults(func=cmd_export_skills)

    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage repo-local Memory OS skill packs.",
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_action", required=True)

    skills_list_parser = skills_subparsers.add_parser("list", help="List local skills.")
    skills_list_parser.add_argument("--skills-dir", default="skills")
    skills_list_parser.add_argument("--format", choices={"text", "json"}, default="text")
    skills_list_parser.set_defaults(func=cmd_skills)

    skills_validate_parser = skills_subparsers.add_parser("validate", help="Validate local skills.")
    skills_validate_parser.add_argument("--skills-dir", default="skills")
    skills_validate_parser.add_argument("--format", choices={"text", "json"}, default="text")
    skills_validate_parser.set_defaults(func=cmd_skills)

    skills_sync_parser = skills_subparsers.add_parser("sync", help="Sync local skills into agent-native directories.")
    skills_sync_parser.add_argument("--skills-dir", default="skills")
    skills_sync_parser.add_argument("--agent", action="append", choices=list(KNOWN_AGENTS) + ["claude-code", "antigravity"])
    skills_sync_parser.add_argument("--dry-run", action="store_true")
    skills_sync_parser.add_argument("--format", choices={"text", "json"}, default="text")
    skills_sync_parser.set_defaults(func=cmd_skills)

    skills_lock_parser = skills_subparsers.add_parser("lock", help="Generate/update deterministic skills.lock.json manifest.")
    skills_lock_parser.add_argument("--skills-dir", default="skills")
    skills_lock_parser.add_argument("--format", choices={"text", "json"}, default="text")
    skills_lock_parser.set_defaults(func=cmd_skills)

    skills_refresh_parser = skills_subparsers.add_parser("refresh", help="Refresh remote-sourced skill packs.")
    skills_refresh_parser.add_argument("name", nargs="?", help="Skill name to refresh. If omitted, requires --all.")
    skills_refresh_parser.add_argument("--all", action="store_true", help="Refresh all remote-sourced skills.")
    skills_refresh_parser.add_argument("--skills-dir", default="skills")
    skills_refresh_parser.add_argument("--format", choices={"text", "json"}, default="text")
    skills_refresh_parser.set_defaults(func=cmd_skills)

    compress_parser = subparsers.add_parser(
        "compress",
        help="Use LLM to semantically merge verified memory nodes.",
    )
    compress_parser.add_argument("--provider", help="Optional provider override (ollama, gemini, groq, openrouter, openai). Default: local Ollama first, then free cloud tiers.")
    compress_parser.add_argument("--model", help="Optional model override")
    compress_parser.add_argument("--dry-run", action="store_true", help="Show what would be merged without writing.")
    compress_parser.set_defaults(func=cmd_compress)

    link_infer_parser = subparsers.add_parser(
        "link-infer",
        help="Automatically discover and add edges between memory nodes.",
    )
    link_infer_parser.add_argument(
        "--method",
        choices=["cascade", "text", "llm", "both"],
        default="cascade",
        help="Edge discovery method: cascade (default — BM25+structural+tags+temporal then LLM on unlinked), text, llm, both.",
    )
    link_infer_parser.add_argument(
        "--resource-mode",
        choices=["quiet", "normal", "max"],
        default=None,
        dest="resource_mode",
        help="Resource budget: quiet (Stage 0 only), normal (+ embeddings when available), max (+ local LM). Defaults to config value.",
    )
    link_infer_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print proposed edges without writing to edges.jsonl.",
    )
    link_infer_parser.add_argument(
        "--min-score",
        type=float,
        default=0.3,
        help="Minimum confidence score for text-matching method (0.0–1.0, default 0.3).",
    )
    link_infer_parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider override (ollama, gemini, groq, openrouter, openai). Default: local Ollama first, then free cloud tiers.",
    )
    link_infer_parser.add_argument(
        "--model",
        default=None,
        help="LLM model override.",
    )
    link_infer_parser.add_argument(
        "--batch-size",
        type=int,
        default=60,
        help="Number of nodes per LLM batch (default 60).",
    )
    link_infer_parser.add_argument(
        "--exclude-types",
        default="",
        help="Comma-separated node types to skip during edge discovery (e.g. 'chat_history,draft').",
    )
    link_infer_parser.set_defaults(func=cmd_link_infer)

    pipeline_parser = subparsers.add_parser(
        "pipeline",
        help="Run a named sequence of memory_os operations in one command.",
    )
    pipeline_parser.add_argument(
        "name",
        nargs="?",
        default="list",
        help="Pipeline name: ingest | refresh | full | custom | list (default: list).",
    )
    pipeline_parser.add_argument(
        "steps",
        nargs="*",
        help="For 'custom' pipeline: sequence of memory_os subcommands to run.",
    )
    pipeline_parser.add_argument("--notion-key", default=None, help="Notion API key (triggers notion-sync step).")
    pipeline_parser.add_argument("--notion-db", default=None, help="Notion database ID.")
    pipeline_parser.add_argument("--provider", default=None, help="LLM provider for LLM steps.")
    pipeline_parser.add_argument("--model", default=None, help="LLM model override.")
    pipeline_parser.add_argument("--dry-run", action="store_true", help="Print steps without executing.")
    pipeline_parser.set_defaults(func=cmd_pipeline)

    prune_parser = subparsers.add_parser(
        "prune",
        help="Archive stale and superseded memory nodes and edges.",
    )
    prune_parser.set_defaults(func=cmd_prune)

    transition_parser = subparsers.add_parser(
        "transition",
        help="Promote observed nodes to verified; handle overrides/refutes deprecation; write manifest.",
    )
    transition_parser.add_argument("--prune", action="store_true", help="Also archive stale/superseded nodes after transition.")
    transition_parser.add_argument("--validator", default="cli_transition", help="Validator name recorded in events.jsonl.")
    transition_parser.add_argument("--min-confidence", type=float, default=None, help="Minimum confidence required to promote draft/observed nodes. Defaults to config confidence_threshold (0.7).")
    transition_parser.set_defaults(func=cmd_transition)

    graph_map_parser = subparsers.add_parser("graph-map", help="Generate codebase graph map or visual HTML graph visualization.")
    graph_map_parser.add_argument("--emit-nodes", action="store_true")
    graph_map_parser.add_argument("--format", choices={"json", "text"}, default="text")
    graph_map_parser.add_argument("--visual", action="store_true", help="Generate interactive HTML visualization of the memory graph.")
    graph_map_parser.add_argument("--html", type=str, default=None, help="Output path for the generated HTML visualization.")
    graph_map_parser.set_defaults(func=cmd_graph_map)

    codebase_parser = subparsers.add_parser("codebase", help="Index source code into the memory graph.")
    codebase_subparsers = codebase_parser.add_subparsers(dest="codebase_action", required=True)
    codebase_index_parser = codebase_subparsers.add_parser(
        "index",
        help="Index src/**/*.py through deterministic domain adapters.",
    )
    codebase_index_parser.add_argument("--source", default="src", help="Source directory relative to project root.")
    codebase_index_parser.add_argument("--protocol-level", type=int, default=4)
    codebase_index_parser.add_argument("--dry-run", action="store_true")
    codebase_index_parser.add_argument("--format", choices={"json", "text"}, default="text")
    codebase_index_parser.set_defaults(func=cmd_codebase)

    linux_parser = subparsers.add_parser("linux", help="Collect, sync, and query Linux/Ubuntu host inventory.")
    linux_subparsers = linux_parser.add_subparsers(dest="linux_action")
    linux_parser.set_defaults(func=cmd_linux)

    linux_inventory_parser = linux_subparsers.add_parser("inventory", help="Collect read-only Linux inventory.")
    linux_inventory_parser.add_argument("--format", choices={"json", "text"}, default="text")
    linux_inventory_parser.add_argument("--write", action="store_true", help="Write agent_context/linux_inventory/latest.json")
    linux_inventory_parser.set_defaults(func=cmd_linux)

    linux_sync_parser = linux_subparsers.add_parser("sync", help="Collect inventory and sync it into the Memory OS graph.")
    linux_sync_parser.add_argument("--format", choices={"json", "text"}, default="text")
    linux_sync_parser.set_defaults(func=cmd_linux)

    linux_query_parser = linux_subparsers.add_parser("query", help="Query synced Linux inventory facts.")
    linux_query_parser.add_argument("query")
    linux_query_parser.add_argument("--limit", type=int, default=25)
    linux_query_parser.add_argument("--format", choices={"json", "text"}, default="text")
    linux_query_parser.set_defaults(func=cmd_linux)

    linux_doctor_parser = linux_subparsers.add_parser("doctor", help="Report Linux inventory issues and human-approved sudo guidance.")
    linux_doctor_parser.set_defaults(func=cmd_linux)

    linux_provision_parser = linux_subparsers.add_parser("provision", help="Idempotently provision UI environments, apps, or tools.")
    linux_provision_parser.add_argument("type", choices={"ui", "tool", "app"})
    linux_provision_parser.add_argument("target", help="Target component (e.g. kde, gnome, firefox, zellij)")
    linux_provision_parser.set_defaults(func=cmd_linux)

    xfce_parser = subparsers.add_parser("xfce", help="Inspect and manage XFCE settings through xfconf-query.")
    xfce_subparsers = xfce_parser.add_subparsers(dest="xfce_action")
    xfce_parser.set_defaults(func=cmd_xfce)

    xfce_status = xfce_subparsers.add_parser("status", help="Show XFCE settings bus availability and channels.")
    xfce_status.add_argument("--json", action="store_true")
    xfce_status.set_defaults(func=cmd_xfce)

    xfce_channels = xfce_subparsers.add_parser("channels", help="List XFCE xfconf channels.")
    xfce_channels.add_argument("--json", action="store_true")
    xfce_channels.set_defaults(func=cmd_xfce)

    xfce_list = xfce_subparsers.add_parser("list", help="List properties in an XFCE channel.")
    xfce_list.add_argument("channel")
    xfce_list.add_argument("--json", action="store_true")
    xfce_list.set_defaults(func=cmd_xfce)

    xfce_get = xfce_subparsers.add_parser("get", help="Read an XFCE property.")
    xfce_get.add_argument("channel")
    xfce_get.add_argument("property")
    xfce_get.set_defaults(func=cmd_xfce)

    xfce_set = xfce_subparsers.add_parser("set", help="Set an XFCE property.")
    xfce_set.add_argument("channel")
    xfce_set.add_argument("property")
    xfce_set.add_argument("value")
    xfce_set.add_argument("--type", choices=sorted({"string", "int", "uint", "bool", "double"}), required=True)
    xfce_set.add_argument("--create", action="store_true", help="Create the property if it does not exist.")
    xfce_set.set_defaults(func=cmd_xfce)

    xfce_reset = xfce_subparsers.add_parser("reset", help="Reset an XFCE property.")
    xfce_reset.add_argument("channel")
    xfce_reset.add_argument("property")
    xfce_reset.add_argument("--recursive", action="store_true")
    xfce_reset.set_defaults(func=cmd_xfce)

    xfce_snapshot = xfce_subparsers.add_parser("snapshot", help="Read all properties from selected XFCE channels.")
    xfce_snapshot.add_argument("--channel", action="append", help="Limit snapshot to one channel; repeatable.")
    xfce_snapshot.add_argument("--json", action="store_true")
    xfce_snapshot.set_defaults(func=cmd_xfce)

    xfce_summary = xfce_subparsers.add_parser("summary", help="Print compact XFCE state summary.")
    xfce_summary.add_argument("--cached", action="store_true", help="Read summary from agent_context/xfce/latest.json.")
    xfce_summary.add_argument("--json", action="store_true")
    xfce_summary.set_defaults(func=cmd_xfce)

    xfce_cache = xfce_subparsers.add_parser("cache", help="Read or write local XFCE state cache.")
    xfce_cache.add_argument("--write", action="store_true", help="Capture full live XFCE state into agent_context/xfce/latest.json.")
    xfce_cache.add_argument("--json", action="store_true")
    xfce_cache.set_defaults(func=cmd_xfce)

    xfce_sync = xfce_subparsers.add_parser("sync", help="Refresh local XFCE cache from live state.")
    xfce_sync.add_argument("--json", action="store_true")
    xfce_sync.set_defaults(func=cmd_xfce)

    xfce_diff = xfce_subparsers.add_parser("diff", help="Compare live XFCE summary against cached summary.")
    xfce_diff.add_argument("--json", action="store_true")
    xfce_diff.set_defaults(func=cmd_xfce)

    xfce_profiles = xfce_subparsers.add_parser("profiles", help="List curated XFCE profiles.")
    xfce_profiles.add_argument("--json", action="store_true")
    xfce_profiles.set_defaults(func=cmd_xfce)

    xfce_apply = xfce_subparsers.add_parser("apply", help="Apply a curated XFCE profile.")
    xfce_apply.add_argument("profile", choices=["memory-workstation", "memory-workstation-4k"])
    xfce_apply.add_argument("--dry-run", action="store_true", help="Print planned changes without applying them.")
    xfce_apply.add_argument("--json", action="store_true")
    xfce_apply.set_defaults(func=cmd_xfce)

    analyze_os_parser = subparsers.add_parser("analyze-os", help=argparse.SUPPRESS)
    analyze_os_parser.add_argument("-v", "--verbose", action="store_true")
    analyze_os_parser.set_defaults(func=cmd_analyze_os)

    giant_scan_parser = subparsers.add_parser("giant-scan", help=argparse.SUPPRESS)
    giant_scan_parser.add_argument("--provider", default="gemini")
    giant_scan_parser.add_argument("--model", default="gemini-2.5-pro")
    giant_scan_parser.add_argument("--force", action="store_true")
    giant_scan_parser.add_argument("--dry-run", action="store_true")
    giant_scan_parser.add_argument("--format", choices={"json", "markdown"}, default="markdown")
    giant_scan_parser.add_argument("--target-dir", default=None)
    giant_scan_parser.set_defaults(func=cmd_giant_scan)

    search_parser = subparsers.add_parser(
        "search",
        help="Query memory runtime nodes, codebase symbols, and traverse relations."
    )
    search_parser.add_argument("query", help="Keyword query or exact symbol.")
    search_parser.add_argument("--depth", type=int, default=1, help="Retrieval traversal recursion depth.")
    search_parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human-readable text.")
    search_parser.add_argument("--semantic", action="store_true", help="Force semantic vector search instead of lexical/keyword search.")
    search_parser.set_defaults(func=cmd_search)

    stats_parser = subparsers.add_parser("stats", help=argparse.SUPPRESS)
    stats_parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human-readable YAML.")
    stats_parser.set_defaults(func=cmd_stats)

    rag_parser = subparsers.add_parser("rag", help=argparse.SUPPRESS)
    rag_parser.add_argument("query")
    rag_parser.set_defaults(func=cmd_rag)

    ingest_parser = subparsers.add_parser("ingest-transcript", help=argparse.SUPPRESS)
    ingest_parser.add_argument("log_file")
    ingest_parser.add_argument("--provider", default="gemini")
    ingest_parser.add_argument("--model", default="")
    ingest_parser.set_defaults(func=cmd_ingest_transcript)

    compile_parser = subparsers.add_parser("compile-prompt", help=argparse.SUPPRESS)
    compile_parser.set_defaults(func=cmd_compile_prompt)

    persona_sync_parser = subparsers.add_parser("persona-sync", help=argparse.SUPPRESS)
    persona_sync_parser.add_argument("log_file")
    persona_sync_parser.add_argument("--provider", default="gemini")
    persona_sync_parser.add_argument("--model", default="")
    persona_sync_parser.set_defaults(func=cmd_persona_sync)

    persona_parser = subparsers.add_parser("persona", help=argparse.SUPPRESS)
    persona_parser.set_defaults(func=cmd_persona)

    daemon_parser = subparsers.add_parser("daemon", help=argparse.SUPPRESS)
    daemon_parser.add_argument("daemon_action", choices=["start", "stop", "status", "sync"])
    daemon_parser.add_argument("--log-file")
    daemon_parser.set_defaults(func=cmd_daemon)

    monitor_parser = subparsers.add_parser("monitor", help=argparse.SUPPRESS)
    monitor_parser.add_argument("--all", action="store_true")
    monitor_parser.set_defaults(func=cmd_monitor)

    internal_daemon_parser = subparsers.add_parser("_run_daemon_blocking", help=argparse.SUPPRESS)
    internal_daemon_parser.add_argument("log_file")
    internal_daemon_parser.set_defaults(func=cmd_run_daemon_blocking)

    review_parser = subparsers.add_parser("review", help="List all draft memory nodes pending human review.")
    review_parser.set_defaults(func=cmd_review)
    
    approve_parser = subparsers.add_parser("approve", help="Approve a draft memory node and mark it as verified.")
    approve_parser.add_argument("node_id", help="ID of the draft node to approve.")
    approve_parser.set_defaults(func=cmd_approve)

    db_optimize_parser = subparsers.add_parser("db-optimize", help=argparse.SUPPRESS)
    db_optimize_parser.set_defaults(func=cmd_db_optimize)

    triage_parser = subparsers.add_parser(
        "triage",
        help="Interactively review draft nodes: approve (observed), reject (stale), tag, or skip.",
    )
    triage_parser.add_argument("--dry-run", action="store_true", help="List draft nodes without prompting.")
    triage_parser.set_defaults(func=cmd_triage)

    query_parser = subparsers.add_parser(
        "query",
        help="Filter memory nodes by metadata (type, trust, status, tag, date).",
    )
    query_parser.add_argument("--type", help="Filter by node type (rule, fact, policy, …)")
    query_parser.add_argument("--trust", help="Filter by trust level (verified, unverified, extracted, inferred)")
    query_parser.add_argument("--status", help="Filter by status (draft, observed, verified, stale, superseded)")
    query_parser.add_argument("--tag", help="Filter by tag (exact match, case-insensitive)")
    query_parser.add_argument("--since", help="Filter nodes with freshness >= ISO date (e.g. 2026-06-01)")
    query_parser.add_argument("--limit", type=int, default=None, help="Maximum nodes to return (default: all).")
    query_parser.add_argument("--offset", type=int, default=0, help="Skip the first N matching nodes.")
    query_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    query_parser.set_defaults(func=cmd_query)

    backlinks_parser = subparsers.add_parser(
        "backlinks",
        help="Show all nodes that reference a given node ID via edges, related_nodes, or text.",
    )
    backlinks_parser.add_argument("node_id", help="Target node ID to look up.")
    backlinks_parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    backlinks_parser.set_defaults(func=cmd_backlinks)

    memory_history_parser = subparsers.add_parser(
        "memory",
        help="Memory history and maintenance — log/show/revert/health/curate/merge for the memory runtime.",
    )
    memory_history_subparsers = memory_history_parser.add_subparsers(dest="memory_action", required=True)

    memory_write_parser = memory_history_subparsers.add_parser("write", help="Record a memory node (agent decision/fact) as a draft candidate through the lifecycle gate.")
    memory_write_parser.add_argument("--type", dest="node_type", default="fact", choices=["fact", "rule", "config", "policy"], help="Node type (default fact).")
    memory_write_parser.add_argument("--summary", required=True, help="The fact/decision text.")
    memory_write_parser.add_argument("--id", dest="node_id", default=None, help="Node id; auto-generated from summary when omitted.")
    memory_write_parser.add_argument("--evidence", default="", help="Comma-separated evidence files/URLs.")
    memory_write_parser.add_argument("--tags", default=None, help="Comma-separated tags.")
    memory_write_parser.add_argument("--confidence", type=float, default=0.8, help="Candidate confidence 0..1 (default 0.8).")
    memory_write_parser.add_argument("--validator", default=None, help="Recorded validator id (defaults to MEMORY_OS_AGENT_ID).")
    memory_write_parser.set_defaults(func=cmd_memory_write)

    memory_log_parser = memory_history_subparsers.add_parser("log", help="Chronological event history, optionally scoped to one node.")
    memory_log_parser.add_argument("--node", default=None, help="Limit to events for this node ID.")
    memory_log_parser.add_argument("--limit", type=int, default=None, help="Show only the most recent N events.")
    memory_log_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_log_parser.set_defaults(func=cmd_memory_log)

    memory_show_parser = memory_history_subparsers.add_parser("show", help="One node's current/archived state plus its full event history.")
    memory_show_parser.add_argument("node_id", help="Node ID to look up.")
    memory_show_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_show_parser.set_defaults(func=cmd_memory_show)

    memory_revert_parser = memory_history_subparsers.add_parser("revert", help="Restore an archived (pruned/superseded) node back as a draft. Does not restore its old edges.")
    memory_revert_parser.add_argument("node_id", help="Node ID to restore from archived_nodes.jsonl.")
    memory_revert_parser.add_argument("--dry-run", action="store_true")
    memory_revert_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_revert_parser.set_defaults(func=cmd_memory_revert)

    memory_normalize_timecodes_parser = memory_history_subparsers.add_parser(
        "normalize-timecodes",
        help="Normalize node/event memory timecodes to offset-aware ISO-8601 in the configured user timezone.",
    )
    memory_normalize_timecodes_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_normalize_timecodes_parser.set_defaults(func=cmd_memory_normalize_timecodes)

    memory_health_parser = memory_history_subparsers.add_parser(
        "health",
        help="Graph health summary: live/archived nodes, edge density, orphan rate, comm noise, and eval readiness.",
    )
    memory_health_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_health_parser.set_defaults(func=cmd_memory_health)

    memory_curate_parser = memory_history_subparsers.add_parser(
        "curate",
        help="Actionable curation queue: merge candidates, connected components, and orphan nodes.",
    )
    memory_curate_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_curate_parser.add_argument("--limit", type=int, default=10, help="Limit merge candidates and components in the report.")
    memory_curate_parser.set_defaults(func=cmd_memory_curate)

    memory_dedup_candidates_parser = memory_history_subparsers.add_parser(
        "dedup-candidates",
        help="Deterministic candidate nodes for deduplication based on embedding cosine similarity >= 0.9 or Jaccard similarity >= 0.8.",
    )
    memory_dedup_candidates_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_dedup_candidates_parser.add_argument("--limit", type=int, default=None, help="Limit the number of candidates.")
    memory_dedup_candidates_parser.set_defaults(func=cmd_memory_dedup_candidates)

    memory_merge_preview_parser = memory_history_subparsers.add_parser(
        "merge-preview",
        help="Preview semantic merge groups with canonical node choice and replacement plan.",
    )
    memory_merge_preview_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_merge_preview_parser.add_argument("--limit", type=int, default=10, help="Limit merge groups in the report.")
    memory_merge_preview_parser.set_defaults(func=cmd_memory_merge_preview)

    memory_merge_apply_parser = memory_history_subparsers.add_parser(
        "merge-apply",
        help="Apply semantic merge groups through patch-backed memory rewrites.",
    )
    memory_merge_apply_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_merge_apply_parser.add_argument("--limit", type=int, default=10, help="Limit merge groups to apply.")
    memory_merge_apply_parser.add_argument("--dry-run", action="store_true", help="Preview the patch-backed merge without writing.")
    memory_merge_apply_parser.set_defaults(func=cmd_memory_merge_apply)

    memory_browse_parser = memory_history_subparsers.add_parser(
        "browse",
        help="Focus a node or query and show its local memory neighborhood.",
    )
    memory_browse_parser.add_argument("query", nargs="?", default="", help="Node ID or search query.")
    memory_browse_parser.add_argument("--node-id", dest="node_id", default=None, help="Explicit node ID to focus.")
    memory_browse_parser.add_argument("--depth", type=int, default=1, help="Search depth when resolving the focus query.")
    memory_browse_parser.add_argument("--limit", type=int, default=3, help="Max focus nodes to show.")
    memory_browse_parser.add_argument("--neighbors", type=int, default=8, help="Max nearby nodes to show per focus node.")
    memory_browse_parser.add_argument("--edges", type=int, default=12, help="Max inbound/outbound edges to show per focus node.")
    memory_browse_parser.add_argument("--format", choices={"json", "text"}, default="text")
    memory_browse_parser.set_defaults(func=cmd_memory_browse)

    unlinked_parser = subparsers.add_parser("unlinked", help=argparse.SUPPRESS)
    unlinked_parser.add_argument("--json", action="store_true")
    unlinked_parser.set_defaults(func=cmd_unlinked)

    if cmd_ide_grant is not None:
        ide_grant_parser = subparsers.add_parser("ide-grant", help=argparse.SUPPRESS)
        ide_grant_parser.set_defaults(func=cmd_ide_grant)

    obsidian_parser = subparsers.add_parser("export-obsidian", help=argparse.SUPPRESS)
    obsidian_parser.set_defaults(func=cmd_export_obsidian)

    linear_parser = subparsers.add_parser("linear-sync", help=argparse.SUPPRESS)
    linear_parser.set_defaults(func=cmd_linear_sync)

    notion_parser = subparsers.add_parser("notion-sync", help="Synchronize memory nodes from a Notion database.")
    notion_parser.add_argument("--api-key", help="Notion Integration Token (NOTION_API_KEY).")
    notion_parser.add_argument("--database-id", help="Notion Database ID (NOTION_DATABASE_ID).")
    notion_parser.add_argument("--to-capsules", action="store_true", help="Import Notion pages as task capsules instead of memory nodes.")
    notion_parser.set_defaults(func=cmd_notion_sync)

    gdrive_parser = subparsers.add_parser("gdrive-sync", help="Synchronize memory nodes from a Google Drive folder.")
    gdrive_parser.add_argument("--token", help="Google Drive Access Token (GDRIVE_ACCESS_TOKEN).")
    gdrive_parser.add_argument("--folder-id", help="Google Drive Folder ID (GDRIVE_FOLDER_ID).")
    gdrive_parser.add_argument("--to-capsules", action="store_true", help="Import Google Drive documents as task capsules instead of memory nodes.")
    gdrive_parser.set_defaults(func=cmd_gdrive_sync)

    ui_parser = subparsers.add_parser("ui", help="Start the Memory OS Visualizer UI server.")
    ui_parser.add_argument("--port", type=int, default=8080, help="Port to run the UI server on.")
    ui_parser.set_defaults(func=cmd_ui)





    doctor_parser = subparsers.add_parser("doctor", help="Check system dependencies, files, DB, and environment.")
    doctor_parser.add_argument("--format", choices={"json", "text"}, default="text")
    doctor_parser.set_defaults(func=cmd_doctor)

    resources_parser = subparsers.add_parser(
        "resources",
        help="Snapshot free disk space, SQLite DB/WAL size, and JSONL size against configured budgets.",
    )
    resources_subparsers = resources_parser.add_subparsers(dest="resources_action")
    resources_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_parser.set_defaults(func=cmd_resources)

    resources_snapshot_parser = resources_subparsers.add_parser("snapshot", help="Report disk/SQLite/JSONL resource health.")
    resources_snapshot_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_snapshot_parser.set_defaults(func=cmd_resources)

    storage_parser = subparsers.add_parser(
        "storage",
        help="Recommend a storage tier (sqlite / local_postgres / cloud_postgres) from measured local signals. Advisory only — never migrates anything.",
    )
    storage_subparsers = storage_parser.add_subparsers(dest="storage_action")
    storage_parser.add_argument("--format", choices={"json", "text"}, default="text")
    storage_parser.set_defaults(func=cmd_storage)

    storage_advise_parser = storage_subparsers.add_parser("advise", help="Report the recommended storage tier and why.")
    storage_advise_parser.add_argument("--format", choices={"json", "text"}, default="text")
    storage_advise_parser.set_defaults(func=cmd_storage)

    resources_compact_parser = resources_subparsers.add_parser("compact", help="Run bounded local resource compaction actions.")
    resources_compact_parser.add_argument("--format", choices={"json", "text"}, default="text")
    resources_compact_parser.add_argument("--dry-run", action="store_true")
    resources_compact_parser.set_defaults(func=cmd_resources)

    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Audit or prune bounded telemetry/performance tables.",
    )
    telemetry_subparsers = telemetry_parser.add_subparsers(dest="telemetry_action", required=True)

    telemetry_audit_parser = telemetry_subparsers.add_parser("audit", help="Report row counts and DB size against configured caps.")
    telemetry_audit_parser.add_argument("--format", choices={"json", "text"}, default="text")
    telemetry_audit_parser.set_defaults(func=cmd_telemetry)

    telemetry_prune_parser = telemetry_subparsers.add_parser("prune", help="Delete rows past retention_days and trim down to max_rows_per_table.")
    telemetry_prune_parser.add_argument("--format", choices={"json", "text"}, default="text")
    telemetry_prune_parser.add_argument("--dry-run", action="store_true", help="Report what would be pruned without deleting anything.")
    telemetry_prune_parser.set_defaults(func=cmd_telemetry)

    release_check_parser = subparsers.add_parser(
        "release-check",
        help="Run deterministic local gates before private or public publishing.",
    )
    release_check_parser.add_argument("--target", choices={"private", "public"}, default="private")
    release_check_parser.add_argument("--format", choices={"json", "text"}, default="text")
    release_check_parser.set_defaults(func=cmd_release_check)

    git_commit_safe_parser = subparsers.add_parser(
        "git-commit-safe",
        help="Stage exactly the given files and commit under a mutex, to avoid sweeping concurrent agents' WIP.",
    )
    git_commit_safe_parser.add_argument("files", nargs="+", help="Files to stage for this commit.")
    git_commit_safe_parser.add_argument("-m", "--message", required=True, help="Commit message.")
    git_commit_safe_parser.set_defaults(func=cmd_git_commit_safe)

    check_updates_parser = subparsers.add_parser(
        "check-updates",
        help="Check the upstream URL for memory_os and read agent contribution rules."
    )
    check_updates_parser.set_defaults(func=cmd_check_updates)

    switch_space_parser = subparsers.add_parser(
        "switch-space",
        help="Switch the background daemon to a different memory space."
    )
    switch_space_parser.add_argument("target_space", help="Name of the space to switch to (e.g. default, user_persona)")
    switch_space_parser.set_defaults(func=cmd_switch_space)

    undo_parser = subparsers.add_parser(
        "undo",
        help="Universal undo command to revert memory events, patch store changes, or git changes for a task.",
    )
    undo_parser.add_argument("--task-id", help="Target task ID to undo.")
    undo_parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without applying changes.")
    undo_parser.add_argument("--json", action="store_true", help="Output result as JSON.")
    undo_parser.set_defaults(func=cmd_undo)

    # ------------------------------------------------------------------ #
    # Agentic OS — Phase 3: Router Plan                                    #
    # ------------------------------------------------------------------ #
    plan_parser = subparsers.add_parser(
        "plan",
        help="Produce an execution plan for a task (Phase 3 — Router Plan).",
    )
    plan_parser.add_argument("--task-id", dest="task_id", default=None,
                             help="Task ID from the task kernel.")
    plan_parser.add_argument("--text", default="", help="Free-text task description (if no task-id).")
    plan_parser.add_argument("--risk", choices=["low", "medium", "high"], default="low")
    plan_parser.add_argument("--capabilities", default="",
                             help="Comma-separated required capabilities (if no task-id).")
    plan_parser.add_argument("--json", action="store_true")
    plan_parser.set_defaults(func=cmd_plan)

    # ------------------------------------------------------------------ #
    # Agentic OS — Phase 4: Dispatch                                       #
    # ------------------------------------------------------------------ #
    dispatch_parser = subparsers.add_parser(
        "dispatch",
        help="Dispatch a task to an agent adapter and write evidence (Phase 4).",
    )
    dispatch_parser.add_argument("--task-id", dest="task_id", default=None)
    dispatch_parser.add_argument("--adapter",
                                 choices=["auto", "shell", "script", "local_model",
                                          "claude", "codex", "agy"],
                                 default="auto",
                                 help="Force a specific adapter (default: auto from RouterPlan).")
    dispatch_parser.add_argument("--cmd", default=None,
                                 help="Command to run (for shell/script adapters).")
    dispatch_parser.add_argument("--text", default="",
                                 help="Prompt text (for local_model adapter).")
    dispatch_parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                                 help="Show what would be dispatched without executing.")
    dispatch_parser.add_argument("--timeout", type=float, default=300.0,
                                 help="Timeout in seconds for CLI agent adapters (default 300).")
    dispatch_parser.add_argument("--json", action="store_true")
    dispatch_parser.set_defaults(func=cmd_dispatch)

    # ------------------------------------------------------------------ #
    # Agentic OS — Handoff Builder                                         #
    # ------------------------------------------------------------------ #
    handoff_parser = subparsers.add_parser(
        "handoff",
        help="Build a handoff context pack markdown for agent-to-agent transitions.",
    )
    handoff_subs = handoff_parser.add_subparsers(dest="handoff_action", required=True)

    handoff_build = handoff_subs.add_parser("build", help="Generate handoff markdown for a task.")
    handoff_build.add_argument("--task-id", dest="task_id", required=True)
    handoff_build.add_argument("--output", default=None,
                               help="Output path (default: agent_context/context_packs/handoff_<id>.md)")
    handoff_build.add_argument("--print", dest="print_output", action="store_true",
                               help="Also print the markdown to stdout.")
    handoff_build.set_defaults(func=cmd_handoff)

    # ------------------------------------------------------------------ #
    # Agent Communication Toolkit                                         #
    # ------------------------------------------------------------------ #
    comm_parser = subparsers.add_parser(
        "comm",
        help="Send tmux-backed inter-agent messages and read compact inbox summaries.",
    )
    comm_subparsers = comm_parser.add_subparsers(dest="comm_action", required=True)

    comm_send = comm_subparsers.add_parser("send", help="Send a message to an agent or orchestrator via tmux.")
    comm_send.add_argument("recipient", help="Target agent id or tmux session alias (claude, codex, agy, ...).")
    comm_send.add_argument("message", help="Message text to send.")
    comm_send.add_argument("--kind", choices=["TASK_ASSIGN", "STATUS_REPORT"], required=True, help="Strict message kind for small-context agents.")
    comm_send.add_argument("--sender", default=None, help="Sender id recorded in the event log.")
    comm_send.add_argument("--task-id", dest="task_id", required=True, help="Task id for event correlation.")
    comm_send.add_argument("--tmux-target", dest="tmux_target", default=None, help="Override the tmux target directly.")
    comm_send.add_argument("--no-unlock", dest="no_unlock", action="store_true", help="Skip Escape/Enter unlock preamble.")
    comm_send.add_argument("--json", action="store_true")
    comm_send.set_defaults(func=cmd_comm)

    comm_inbox = comm_subparsers.add_parser("inbox", help="Show active tasks and UNREAD messages; advances the read cursor.")
    comm_inbox.add_argument("--recipient", default=None, help="Inbox owner; defaults to MEMORY_OS_AGENT_ID or claude.")
    comm_inbox.add_argument("--task-id", dest="task_id", default=None, help="Limit to one task id (does not advance cursor).")
    comm_inbox.add_argument("--limit", type=int, default=20, help="Max tasks/messages to show.")
    comm_inbox.add_argument("--all", action="store_true", help="Show already-read messages too.")
    comm_inbox.add_argument("--peek", action="store_true", help="Show unread without advancing the cursor.")
    comm_inbox.add_argument("--rewind", action="store_true", help="Reset the read cursor to 0 before listing.")
    comm_inbox.add_argument("--json", action="store_true")
    comm_inbox.set_defaults(func=cmd_comm)

    comm_read = comm_subparsers.add_parser("read", help="Print the full body of one inbox message by its [#id].")
    comm_read.add_argument("msg_id", type=int, help="Message id shown as [#N] in inbox listing.")
    comm_read.add_argument("--recipient", default=None, help="Inbox owner; defaults to MEMORY_OS_AGENT_ID or claude.")
    comm_read.add_argument("--json", action="store_true")
    comm_read.set_defaults(func=cmd_comm)

    comm_rotate = comm_subparsers.add_parser("rotate", help="Archive old event/inbox log lines, keeping the hot tail; read cursors are rebased.")
    comm_rotate.set_defaults(func=cmd_comm)

    comm_status = comm_subparsers.add_parser("status", help="Show tmux connectivity and recent comm activity.")
    comm_status.add_argument("--json", action="store_true")
    comm_status.set_defaults(func=cmd_comm)

    comm_resume = comm_subparsers.add_parser("resume", help="Show a compact resume report after context loss or chat reset.")
    comm_resume.add_argument("--limit", type=int, default=5, help="Max completed STATUS_REPORT events to include.")
    comm_resume.add_argument("--json", action="store_true")
    comm_resume.set_defaults(func=cmd_comm)

    comm_feed = comm_subparsers.add_parser("feed", help="Show live timeline of inter-agent communication events.")
    comm_feed.add_argument("--limit", type=int, default=30, help="Max events to show.")
    comm_feed.add_argument("--json", action="store_true")
    comm_feed.add_argument("--new", action="store_true", help="Only events since the last --new call (global cursor).")
    comm_feed.add_argument("--watch", action="store_true", help="Tail task_events.jsonl in real-time (Ctrl-C to stop).")
    comm_feed.set_defaults(func=cmd_comm)

    feed_parser = subparsers.add_parser("feed", help="Show live timeline of inter-agent communication events.")
    feed_parser.add_argument("--limit", type=int, default=30, help="Max events to show.")
    feed_parser.add_argument("--json", action="store_true")
    feed_parser.add_argument("--new", action="store_true", help="Only events since the last --new call (global cursor).")
    feed_parser.add_argument("--watch", action="store_true", help="Tail task_events.jsonl in real-time (Ctrl-C to stop).")
    feed_parser.set_defaults(func=lambda args, config: cmd_comm(argparse.Namespace(comm_action="feed", root=args.root, limit=args.limit, json=args.json, new=args.new, watch=args.watch), config))

    # ------------------------------------------------------------------ #
    # Tmux Automation & Control                                          #
    # ------------------------------------------------------------------ #
    tmux_parser = subparsers.add_parser(
        "tmux",
        help="Automated tmux control, prompt dispatch, shortcuts, and pane capturing for agents.",
    )
    tmux_subparsers = tmux_parser.add_subparsers(dest="tmux_action", required=True)

    tmux_send = tmux_subparsers.add_parser("send", help="Send keys and message text to a target tmux pane.")
    tmux_send.add_argument("target", help="Tmux target pane (e.g. memory_os_workspace:0.1 or 0).")
    tmux_send.add_argument("message", help="Message text to send.")
    tmux_send.add_argument("--no-submit", action="store_true", help="Do not send Enter/C-m submission keys after text.")
    tmux_send.add_argument("--no-unlock", action="store_true", help="Skip Escape/Enter unlock preamble.")
    tmux_send.set_defaults(func=cmd_tmux)

    tmux_shortcut = tmux_subparsers.add_parser("shortcut", help="Send a control shortcut to a target tmux pane.")
    tmux_shortcut.add_argument("target", help="Tmux target pane.")
    tmux_shortcut.add_argument("name", choices=["cancel", "clear", "exit", "detach", "toggle_auto", "page_up", "page_down", "next_window", "previous_window", "unlock"], help="Shortcut name.")
    tmux_shortcut.set_defaults(func=cmd_tmux)

    tmux_press = tmux_subparsers.add_parser("press", help="Send special keys or sequence (e.g. up, down, enter, escape, tab) to a pane.")
    tmux_press.add_argument("target", help="Target pane.")
    tmux_press.add_argument("keys", nargs="+", help="One or more keys to send (e.g. up down enter space a b c).")
    tmux_press.set_defaults(func=cmd_tmux)


    tmux_capture = tmux_subparsers.add_parser("capture", help="Capture tail output from a tmux pane.")
    tmux_capture.add_argument("target", help="Tmux target pane.")
    tmux_capture.add_argument("--lines", type=int, default=50, help="Number of lines to capture.")
    tmux_capture.set_defaults(func=cmd_tmux)

    tmux_list = tmux_subparsers.add_parser("list", help="List active tmux panes and commands.")
    tmux_list.add_argument("--session", default=None, help="Filter by session name.")
    tmux_list.add_argument("--json", action="store_true")
    tmux_list.set_defaults(func=cmd_tmux)


    # ------------------------------------------------------------------ #
    # Telegram Polling Daemon                                             #
    # ------------------------------------------------------------------ #
    tg_daemon_parser = subparsers.add_parser(
        "telegram-daemon",
        help="Start the Telegram long-polling loop (get_updates → ActionBrain → Responder → send_message).",
    )
    tg_daemon_parser.add_argument("--poll-interval", dest="poll_interval", type=float, default=2.0,
                                  help="Seconds between get_updates calls (default 2.0).")
    tg_daemon_parser.add_argument("--provider", default=None, help="Override LLM provider (llama_cpp, ollama, …).")
    tg_daemon_parser.add_argument("--model", default=None, help="Override LLM model name.")
    tg_daemon_parser.add_argument("--system-prompt", dest="system_prompt", default=None,
                                  help="Override responder system prompt.")
    tg_daemon_parser.add_argument("--once", action="store_true",
                                  help="Process one update batch and exit (useful for testing).")
    tg_daemon_parser.add_argument("--no-task-tracking", dest="no_task_tracking",
                                  action="store_true",
                                  help="Disable Task Kernel integration (don't create tasks per message).")
    tg_daemon_parser.add_argument("--swarm-control", dest="swarm_control",
                                  action="store_true",
                                  help="Enable deterministic Telegram swarm-control commands (/task, /swarm, /status, /search).")
    tg_daemon_parser.add_argument("--swarm-watch-timeout", dest="swarm_watch_timeout", type=float, default=10.0,
                                  help="Seconds to wait for STATUS_REPORT after dispatch before returning to polling.")
    tg_daemon_parser.add_argument("--max-retries", dest="max_retries", type=int, default=5,
                                  help="Max consecutive get_updates failures before stopping (default 5).")
    tg_daemon_parser.set_defaults(func=cmd_telegram_daemon)

    tg_control_parser = subparsers.add_parser(
        "telegram-daemon-control",
        help="Manage the Telegram swarm-control daemon as a detached local process.",
    )
    tg_control_parser.add_argument("telegram_daemon_action", choices=["start", "stop", "restart", "status"])
    tg_control_parser.add_argument("--poll-interval", dest="poll_interval", type=float, default=2.0)
    tg_control_parser.add_argument("--swarm-watch-timeout", dest="swarm_watch_timeout", type=float, default=0)
    tg_control_parser.add_argument("--no-task-tracking", dest="no_task_tracking", action="store_true")
    tg_control_parser.add_argument("--force", action="store_true", help="For stop/restart: use SIGKILL if SIGTERM does not exit.")
    tg_control_parser.set_defaults(func=cmd_telegram_daemon_control)

    # ------------------------------------------------------------------ #
    # Agentic OS — Task Kernel (Phase 1)                                   #
    # ------------------------------------------------------------------ #
    task_parser = subparsers.add_parser("task", help="File-backed task kernel (create, list, claim, status…)")
    task_subs = task_parser.add_subparsers(dest="task_action", required=True)

    task_create = task_subs.add_parser("create", help="Create a new task.")
    task_create.add_argument("--title", required=True, help="Short task title.")
    task_create.add_argument("--goal", default="", help="Detailed goal description.")
    task_create.add_argument("--risk", choices=["low", "medium", "high"], default="low")
    task_create.add_argument("--capabilities", default="", help="Comma-separated required capabilities.")
    task_create.add_argument("--done-criteria", dest="done_criteria", default=None)
    task_create.add_argument("--json", action="store_true")
    task_create.set_defaults(func=cmd_task)

    task_list = task_subs.add_parser("list", help="List tasks, optionally filtered.")
    task_list.add_argument("--status", choices=["pending", "claimed", "running", "blocked", "review", "done"], default=None)
    task_list.add_argument("--agent", default=None, help="Filter by assigned agent id.")
    task_list.add_argument("--risk", choices=["low", "medium", "high"], default=None)
    task_list.add_argument("--json", action="store_true")
    task_list.set_defaults(func=cmd_task)

    task_status = task_subs.add_parser("status", help="Show full status of a task including event history.")
    task_status.add_argument("task_id")
    task_status.add_argument("--json", action="store_true")
    task_status.set_defaults(func=cmd_task)

    task_claim = task_subs.add_parser("claim", help="Claim a pending task for an agent.")
    task_claim.add_argument("task_id")
    task_claim.add_argument("--agent", required=True, help="Agent id claiming the task.")
    task_claim.add_argument("--lease-minutes", dest="lease_minutes", type=int, default=30)
    task_claim.set_defaults(func=cmd_task)

    task_start = task_subs.add_parser("start", help="Transition claimed → running.")
    task_start.add_argument("task_id")
    task_start.set_defaults(func=cmd_task)

    task_block = task_subs.add_parser("block", help="Block a running/claimed task.")
    task_block.add_argument("task_id")
    task_block.add_argument("--reason", required=True)
    task_block.set_defaults(func=cmd_task)

    task_review = task_subs.add_parser("review", help="Move running task to review.")
    task_review.add_argument("task_id")
    task_review.add_argument("--summary", default=None)
    task_review.set_defaults(func=cmd_task)

    task_done = task_subs.add_parser("done", help="Mark a task as done.")
    task_done.add_argument("task_id")
    task_done.add_argument("--summary", default=None)
    task_done.set_defaults(func=cmd_task)

    task_unclaim = task_subs.add_parser("unclaim", help="Release a claim; task returns to pending.")
    task_unclaim.add_argument("task_id")
    task_unclaim.set_defaults(func=cmd_task)

    task_leases = task_subs.add_parser("leases", help="Show active and stale leases.")
    task_leases.add_argument("--json", action="store_true")
    task_leases.set_defaults(func=cmd_task)

    task_events = task_subs.add_parser("events", help="Show task event log.")
    task_events.add_argument("task_id", nargs="?", default=None, help="Filter to this task id (all if omitted).")
    task_events.add_argument("--limit", type=int, default=None)
    task_events.add_argument("--json", action="store_true")
    task_events.set_defaults(func=cmd_task)

    # ------------------------------------------------------------------ #
    # Agentic OS — Agent Registry (Phase 2)                               #
    # ------------------------------------------------------------------ #
    agent_reg_parser = subparsers.add_parser("agent-registry", help="Agent registry — list and audit configured agents.")
    agent_reg_subs = agent_reg_parser.add_subparsers(dest="registry_action", required=True)

    agent_reg_list = agent_reg_subs.add_parser("list", help="List all registered agents.")
    agent_reg_list.set_defaults(func=cmd_agent_registry)

    agent_reg_audit = agent_reg_subs.add_parser("audit", help="Audit agent CLIs — check which binaries are available.")
    agent_reg_audit.set_defaults(func=cmd_agent_registry)

    agent_reg_health = agent_reg_subs.add_parser("health", help="Check agent responsiveness, binaries, and quotas (AgentHealthProbe).")
    agent_reg_health.add_argument("--force", action="store_true", help="Bypass cache and run real probe checks.")
    agent_reg_health.add_argument("--json", action="store_true", help="Output results as JSON.")
    agent_reg_health.set_defaults(func=cmd_agent_registry)

    agent_mgr_parser = subparsers.add_parser("agent-manager", help="Launch interactive TUI agent quota and pane manager.")
    agent_mgr_parser.add_argument("--status", action="store_true", help="Print agent status table and exit.")
    agent_mgr_parser.add_argument("--json", action="store_true", help="Print agent status as JSON and exit.")
    agent_mgr_parser.add_argument("--plain", action="store_true", help="Run plain text interactive mode.")
    agent_mgr_parser.add_argument("--probe-usage", dest="probe_usage", action="store_true", help="Inject /usage into idle agent panes, harvest percentages, print status.")
    agent_mgr_parser.add_argument("--restart-all", dest="restart_all", action="store_true", help="Restart Memory OS daemon, Telegram daemon, and workspace runtime.")
    agent_mgr_parser.add_argument("--shutdown-all", dest="shutdown_all", action="store_true", help="Stop Memory OS daemon, Telegram daemon, and workspace runtime.")
    agent_mgr_parser.add_argument("--force", action="store_true", help="Use forceful stop where the underlying process supports it.")
    agent_mgr_parser.add_argument("--no-detach", dest="no_detach", action="store_true", help=argparse.SUPPRESS)
    agent_mgr_parser.add_argument("--workspace-only", dest="workspace_only", action="store_true", help=argparse.SUPPRESS)
    agent_mgr_parser.set_defaults(func=cmd_agent_manager)

    ls_parser = subparsers.add_parser("ls", help="List running memory_os instances (workspace + daemon).")
    ls_parser.add_argument("--json", action="store_true", help="Output as JSON.")
    ls_parser.set_defaults(func=cmd_ls)

    zellij_parser = subparsers.add_parser("zellij", help="Launch the Memory OS workspace in Zellij.")
    zellij_parser.set_defaults(func=cmd_zellij)

    killall_parser = subparsers.add_parser("killall", help="Stop and close all Memory OS processes, daemons, tmux and Zellij sessions/panes.")
    killall_parser.set_defaults(func=cmd_killall)

    swarm_send_parser = subparsers.add_parser(
        "swarm-send", help="Send a task to an agent pane with swarm completion protocol."
    )
    swarm_send_parser.add_argument("--agent", required=True, choices=list(KNOWN_AGENTS) + ["local"], help="Target agent.")
    swarm_send_parser.add_argument("--task-id", required=True, dest="task_id", help="Task ID from task kernel.")
    swarm_send_parser.add_argument("--prompt", required=True, help="Task instructions for the agent.")
    swarm_send_parser.add_argument("--sender", default=None, help="Sender agent ID (default: MEMORY_OS_AGENT_ID env var, or 'claude').")
    swarm_send_parser.add_argument("--effort", choices=["low", "medium", "high"], default="", help="Override quantizer-derived effort tier in the [EFFORT] task header.")
    swarm_send_parser.set_defaults(func=cmd_swarm_send)

    swarm_watch_parser = subparsers.add_parser(
        "swarm-watch", help="Block until an agent sends STATUS_REPORT for a task, then print the result."
    )
    swarm_watch_parser.add_argument("--task-id", required=True, dest="task_id", help="Task ID to wait for.")
    swarm_watch_parser.add_argument("--timeout", type=int, default=300, help="Max seconds to wait (default 300).")
    swarm_watch_parser.set_defaults(func=cmd_swarm_watch)

    install_parser = subparsers.add_parser(
        "install", help="Run universal system bootstrap and agent framework environment diagnostics."
    )
    install_parser.add_argument("--force", action="store_true", help="Force re-running full environment bootstrap check.")
    install_parser.add_argument("--dry-run", action="store_true", help="Report diagnostic status without making system changes.")
    install_parser.add_argument("--json", action="store_true", help="Output diagnostic results as JSON.")
    install_parser.set_defaults(func=cmd_install)

    ws_parser = subparsers.add_parser("workspace", help="Manage registered workspace profiles in ~/.memory_os/workspaces.toml.")
    ws_subs = ws_parser.add_subparsers(dest="workspace_action")
    ws_parser.set_defaults(func=cmd_workspace)

    ws_list_parser = ws_subs.add_parser("list", help="List registered workspaces.")
    ws_list_parser.add_argument("--json", action="store_true")
    ws_list_parser.set_defaults(func=cmd_workspace)

    ws_reg_parser = ws_subs.add_parser("register", help="Register current or specified workspace path.")
    ws_reg_parser.add_argument("path", nargs="?", default=None)
    ws_reg_parser.add_argument("--name", default=None)
    ws_reg_parser.set_defaults(func=cmd_workspace)

    ws_unreg_parser = ws_subs.add_parser("unregister", help="Unregister workspace by slug or path.")
    ws_unreg_parser.add_argument("name")
    ws_unreg_parser.set_defaults(func=cmd_workspace)

    ws_tg_parser = ws_subs.add_parser("telegram-token", help="Configure or check a project-local Telegram bot token.")
    ws_tg_parser.add_argument("path", nargs="?", default=None, help="Workspace path. Defaults to current --root/config workspace.")
    ws_tg_parser.add_argument("--stdin", action="store_true", help="Read TELEGRAM_BOT_TOKEN from stdin.")
    ws_tg_parser.add_argument("--check", action="store_true", help="Return whether project .env has TELEGRAM_BOT_TOKEN.")
    ws_tg_parser.set_defaults(func=cmd_workspace)

    ws_status_parser = ws_subs.add_parser("status", help="Show current workspace runtime status without launching or attaching.")
    ws_status_parser.add_argument("--runtime", choices=["auto", "tmux", "zellij", "file"], default="auto")
    ws_status_parser.add_argument("--json", action="store_true")
    ws_status_parser.set_defaults(func=cmd_workspace)

    ws_clean_parser = ws_subs.add_parser("clean-exited", help="List or delete EXITED workspace runtime sessions.")
    ws_clean_parser.add_argument("--runtime", choices=["zellij"], default="zellij")
    ws_clean_parser.add_argument("--apply", action="store_true", help="Actually delete listed EXITED sessions. Default is dry-run.")
    ws_clean_parser.add_argument("--json", action="store_true")
    ws_clean_parser.set_defaults(func=cmd_workspace)

    ws_restart_parser = ws_subs.add_parser("restart-pane", help="Restart a specific agent/pane process in the workspace.")
    ws_restart_parser.add_argument("name", help="Name of the agent/pane to restart (e.g. agent-manager, claude, codex, agy, telegram-chat).")
    ws_restart_parser.set_defaults(func=cmd_workspace)

    return parser


def main() -> int:
    if len(sys.argv) == 1:
        from memory_os.toolkit.bootstrap_installer import run_bootstrap
        run_bootstrap(interactive=True)
        if shutil.which("tmux") or shutil.which("zellij"):
            from memory_os.toolkit.project_picker import select_workspace
            from memory_os.toolkit.workspace import launch_workspace
            from memory_os.toolkit.workspace_runtime import handle_workspace_menu_action
            target_path = select_workspace()
            if target_path is not None:
                runtime_result = handle_workspace_menu_action(target_path)
                if runtime_result and runtime_result.handled:
                    if runtime_result.message:
                        print(runtime_result.message)
                    return 0
                if isinstance(target_path, Path):
                    from memory_os.toolkit.startup_profile import select_startup_profile
                    profile = select_startup_profile()
                    launch_workspace(target_path, profile=profile)
                    return 0
        parser = build_parser()
        parser.print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args()
    
    config_path = args.config
    if not config_path and args.root:
        # Always derive config_path from --root, even if the config file
        # doesn't exist there yet — MemoryOSConfig already defaults missing
        # config to built-in values, and root_dir comes from config_path's
        # parent, so falling through to cwd here would silently operate on
        # the wrong directory instead of the one the caller asked for.
        root_path = Path(args.root).resolve()
        config_path = str(root_path / "memory_os.config.json")

    if config_path:
        os.environ["MEMORY_OS_CONFIG_PATH"] = config_path
    else:
        # Default to current working directory if no root or config given
        config_path = str(Path.cwd() / "memory_os.config.json")
        
    config = MemoryOSConfig(config_path, space=args.space)
    return args.func(args, config)

if __name__ == "__main__":
    raise SystemExit(main())