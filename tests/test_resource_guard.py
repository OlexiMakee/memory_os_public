import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.core.resource_guard import ResourceGuard


def _config(tmp_path: Path, resources: dict) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"memory_dir": "memory", "db_path": "memory/memory_os.db", "resources": resources}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def test_resource_guard_uses_hardcoded_defaults_without_config():
    guard = ResourceGuard()
    assert guard.max_cpu == 75.0
    assert guard.max_ram == 85.0
    assert guard.max_temp == 80.0


def test_resource_guard_reads_thresholds_from_config(tmp_path):
    """Regression: ResourceGuard() ignored memory_os.config.json entirely, unlike
    DiskGuard's config.data.get("resources", {}) pattern -- every call site had no
    way to tune CPU/RAM/temp ceilings without editing source.
    """
    config = _config(tmp_path, {"max_cpu": 50.0, "max_ram": 60.0, "max_temp": 70.0})

    guard = ResourceGuard(config=config)

    assert guard.max_cpu == 50.0
    assert guard.max_ram == 60.0
    assert guard.max_temp == 70.0


def test_resource_guard_explicit_kwargs_win_over_config(tmp_path):
    config = _config(tmp_path, {"max_cpu": 50.0})

    guard = ResourceGuard(max_cpu=90.0, config=config)

    assert guard.max_cpu == 90.0


def test_resource_guard_partial_config_falls_back_to_defaults(tmp_path):
    config = _config(tmp_path, {"max_cpu": 40.0})

    guard = ResourceGuard(config=config)

    assert guard.max_cpu == 40.0
    assert guard.max_ram == 85.0
    assert guard.max_temp == 80.0
