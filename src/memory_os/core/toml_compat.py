"""Single source of truth for tomllib/tomli fallback (Python <3.11 support)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def toml_module() -> Any:
    try:
        import tomllib

        return tomllib
    except ImportError:
        import tomli

        return tomli


def load_toml_text(text: str) -> Dict[str, Any]:
    return toml_module().loads(text)


def load_toml_path(path: Path) -> Dict[str, Any]:
    with Path(path).open("rb") as fh:
        return toml_module().load(fh)
