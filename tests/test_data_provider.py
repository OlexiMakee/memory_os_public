import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.ui.data_provider import DefaultGraphDataProvider


def _config(root: Path) -> MemoryOSConfig:
    (root / "memory").mkdir()
    (root / "agent_context").mkdir()
    (root / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(config_path=str(root / "memory_os.config.json"))


def test_resolve_file_path_rglob_fallback_is_deterministic(tmp_path):
    """Ambiguous basenames must resolve to a stable pick, not filesystem-order-dependent luck.

    Regression: _resolve_file_path used to return rglob()'s first hit unsorted, so which of two
    same-named files under different directories got served through /api/read_file could vary
    by OS/filesystem — a correctness gap in a path-confinement boundary function.
    """
    config = _config(tmp_path)
    provider = DefaultGraphDataProvider(config)

    (tmp_path / "zdir").mkdir()
    (tmp_path / "zdir" / "notes.md").write_text("z", encoding="utf-8")
    (tmp_path / "adir").mkdir()
    (tmp_path / "adir" / "notes.md").write_text("a", encoding="utf-8")

    missing_hint = str(tmp_path / "does-not-exist" / "notes.md")
    resolved = provider._resolve_file_path(missing_hint, tmp_path.resolve())

    assert resolved == (tmp_path / "adir" / "notes.md").resolve()
