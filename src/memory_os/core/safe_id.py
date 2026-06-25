"""Shared path-safety helpers.

Centralizes two checks that several modules need whenever a caller-supplied
string becomes part of a filesystem path: a slug check for single path
segments (task_id, feature_id, run_id, ...) and a containment check for
paths that may include subdirectories (contract files, configured data
paths, ...). One place to get this right instead of every call site
re-implementing (or forgetting) its own version.
"""

from __future__ import annotations

import re
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_safe_id(value: str, label: str = "id") -> str:
    """Raise ValueError unless `value` is safe to use as a single path segment.

    Rejects path separators, '..', '.', empty strings, and anything outside a
    conservative slug charset. The leading-character restriction alone is
    enough to reject '.' and '..' since neither starts with [A-Za-z0-9].
    """
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise ValueError(
            f"invalid {label} {value!r}: must match letters/digits/'.'/'_'/'-' "
            "only, with no path separators, and must not start with '.'"
        )
    return value


def validate_safe_node_id(value: str, label: str = "node id") -> str:
    """Like validate_safe_id, but also allows ':' for memory-graph node IDs.

    Node IDs use an established 'file:queue.py' / 'class:TaskQueue' style
    namespace convention (see core/adapters.py) that validate_safe_id's
    stricter charset would reject. ':' is not a path separator on any
    platform this project targets, so it's safe to allow here while still
    rejecting '/', '\\\\', and any leading '.' (which blocks '../' traversal
    the same way validate_safe_id does).
    """
    if not isinstance(value, str) or not _SAFE_NODE_ID_RE.match(value):
        raise ValueError(
            f"invalid {label} {value!r}: must match letters/digits/'.'/'_'/'-'/':' "
            "only, with no path separators, and must not start with '.'"
        )
    return value


def confine_to_root(path_str: str, root: Path) -> Path:
    """Resolve `path_str` against `root` and require the result to stay inside it.

    Accepts both relative paths (joined to root) and absolute paths (resolved
    as-is); either way the resolved path must end up under `root`, or this
    raises ValueError instead of silently reading/writing outside the project.
    """
    root_resolved = Path(root).resolve()
    candidate = Path(path_str)
    resolved = candidate.resolve() if candidate.is_absolute() else (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"path {path_str!r} resolves outside project root {root_resolved}")
    return resolved


def validate_outbound_base_url(base_url: Optional[str], label: str = "base_url") -> None:
    """Raise ValueError for a caller-supplied LLM endpoint that targets the
    cloud metadata range, the classic cloud-SSRF target (e.g. a configured
    base_url pointed at 169.254.169.254 instead of the intended local/LAN
    inference server). Deliberately does NOT block ordinary private/LAN
    ranges or localhost — those are legitimate for self-hosted local
    inference (vLLM, Ollama, etc.), which is the whole point of these
    adapters.
    """
    if base_url is None:
        return

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{label} must use http or https")

    host = parsed.hostname
    if host is None:
        raise ValueError(f"{label} must include a host")

    try:
        address = ip_address(host)
    except ValueError:
        return

    if address in ip_network("169.254.0.0/16"):
        raise ValueError(f"{label} must not target link-local metadata addresses")
