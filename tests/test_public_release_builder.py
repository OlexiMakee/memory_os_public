"""Unit tests for Clean-Room Public Release Exporter."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_builder():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_public_release.py"
    spec = importlib.util.spec_from_file_location("build_public_release", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_clean_room_export_strips_forbidden_paths_and_passes_gate(tmp_path: Path):
    builder = _load_builder()
    source_root = Path(__file__).resolve().parents[1]
    staging = tmp_path / "public_stage"

    result = builder.export_clean_room_tree(source_root, staging)

    assert result["ok"] is True, f"Clean-room gate failed: {result['checks']}"
    assert (staging / "pyproject.toml").is_file()
    assert (staging / "action.yml").is_file()
    assert (staging / "README.md").is_file()
    assert (staging / "docs" / "LAUNCH_PACK.md").is_file()
    assert (staging / "src" / "memory_os" / "core" / "timecode.py").is_file()
    assert not (staging / "src" / "memory_os" / "ide_grant_private.py").exists()
    assert not (staging / "src" / "memory_os" / "user_persona").exists()
    assert not (staging / "src" / "memory_os" / "lora").exists()
    # PRODUCT_BOUNDARY.md CUT modules stay synchronized and stripped
    for cut_rel in (
        "src/memory_os/toolkit/startup_profile.py",
        "src/memory_os/toolkit/bootstrap_installer.py",
        "src/memory_os/adapters/telegram_adapter.py",
        "src/memory_os/adapters/discord_adapter.py",
        "src/memory_os/agent_brain",
        "src/memory_os/toolkit/multiplexer_manager.py",
        "src/memory_os/toolkit/quota_harvester.py",
        "src/memory_os/toolkit/quantizer.py",
        "src/memory_os/adapters/duckdb_adapter.py",
        "src/memory_os/adapters/bridges",
        "src/memory_os/toolkit/gdrive_sync.py",
    ):
        assert not (staging / cut_rel).exists(), f"CUT path leaked into public staging: {cut_rel}"
