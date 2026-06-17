"""
LOCAL FIRST Engine Template
===========================
Copy this file to your project as `scripts/<domain>_engine.py` and adapt.

Principle: build a CLI tool once so agents never write ad-hoc code or queries.
Pair with a skill file at `media_skills/<domain>_engine_skill.md` (see template).

Real-world example: scripts/analytics_engine.py in news-research projects.

Usage pattern:
    python scripts/<domain>_engine.py <command> --<arg> <value>
    python scripts/<domain>_engine.py <command> --output json | jq .

Checklist before shipping:
  [ ] All commands have --output markdown|json
  [ ] Write commands have --dry-run flag
  [ ] Default DB / data path auto-resolved from project root
  [ ] Paired skill file written and committed to memory_os
"""

import sys
import json
from pathlib import Path

import click

# Resolve project root so the script works from any working directory
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Replace these imports with your project's actual modules
# ---------------------------------------------------------------------------
# from scripts.<domain>.detector import detect, to_json, to_markdown
# from scripts.<domain>.ranker   import rank,   to_json as rank_json, to_markdown as rank_md

_DEFAULT_DB = str(_ROOT / "data" / "main.db")   # adapt to your DB path


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="1.0.0")
def cli():
    """<Domain> Engine — unified data analysis. Replace this docstring."""


# ---------------------------------------------------------------------------
# Command 1: detect / scan (read-only, safe to run autonomously)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--source", required=True, help="Source name or ID to analyse.")
@click.option("--threshold", type=float, default=2.5, show_default=True,
              help="Detection threshold.")
@click.option("--output", type=click.Choice(["markdown", "json"]),
              default="markdown", show_default=True)
@click.option("--db-path", default=_DEFAULT_DB, show_default=True)
@click.option("--verbose", is_flag=True)
def detect(source: str, threshold: float, output: str, db_path: str, verbose: bool):
    """Detect anomalies / outliers for a source. (Replace with your logic.)"""
    try:
        # results, summary = detect(source=source, threshold=threshold, db_path=db_path, verbose=verbose)
        # if output == "json":
        #     click.echo(to_json(results, summary))
        # else:
        #     click.echo(to_markdown(results, summary))
        click.echo(json.dumps({"source": source, "threshold": threshold, "results": []}, indent=2))
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command 2: rank / top (read-only)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--source", required=True, help="Source name or ID.")
@click.option("--metric", default="score", show_default=True,
              help="Metric to rank by.")
@click.option("--limit", type=int, default=10, show_default=True)
@click.option("--days",  type=int, default=30,  show_default=True,
              help="Lookback window in days.")
@click.option("--output", type=click.Choice(["markdown", "json"]),
              default="markdown", show_default=True)
@click.option("--db-path", default=_DEFAULT_DB, show_default=True)
def rank(source: str, metric: str, limit: int, days: int, output: str, db_path: str):
    """Top N items by metric for a source. (Replace with your logic.)"""
    try:
        # results = rank(source=source, metric=metric, limit=limit, days=days, db_path=db_path)
        # click.echo(rank_json(results) if output == "json" else rank_md(results))
        click.echo(json.dumps({"source": source, "metric": metric, "limit": limit, "results": []}, indent=2))
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Command 3: summarise / tags / keywords (read-only)
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--source", default=None, help="Source name or ID (omit = all).")
@click.option("--ngram",  type=click.IntRange(1, 4), default=2, show_default=True)
@click.option("--limit",  type=int, default=20, show_default=True)
@click.option("--days",   type=int, default=None,
              help="Lookback in days (default: all time).")
@click.option("--output", type=click.Choice(["markdown", "json"]),
              default="markdown", show_default=True)
@click.option("--db-path", default=_DEFAULT_DB, show_default=True)
def tags(source, ngram: int, limit: int, days, output: str, db_path: str):
    """Phrase / keyword performance. (Replace with your logic.)"""
    try:
        # report = analyse_phrases(source=source, ngram_min=ngram, ngram_max=ngram,
        #                          limit=limit, days=days, db_path=db_path)
        # click.echo(phrase_json(report) if output == "json" else phrase_md(report))
        click.echo(json.dumps({"source": source, "ngram": ngram, "limit": limit, "results": []}, indent=2))
    except Exception as exc:
        click.echo(f"ERROR: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
