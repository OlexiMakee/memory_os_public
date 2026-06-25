"""Shared file-safety policy for context, ingest, and security tooling."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from memory_os.core.safe_id import confine_to_root


PRIVATE_EXACT_PATHS = {
    "DEV_STRATEGY.md",
    "agent_context/IMPORTANT_PROPOSAL.md",
}

PRIVATE_PREFIXES = (
    "agent_context/audits/",
    "agent_context/private/",
)

SECRET_PATH_MARKERS = (
    ".env",
    "secret",
    "credential",
)


@dataclass(frozen=True)
class FilePolicyDecision:
    allowed: bool
    reason: str = ""


def normalize_rel_path(path: Union[Path, str]) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def load_export_ignore_patterns(root: Path) -> List[str]:
    """Read the subset of .gitattributes patterns that use export-ignore.

    This intentionally implements only the conservative matching Memory OS
    needs: exact paths, directory prefixes, and fnmatch globs.
    """
    attrs_path = root / ".gitattributes"
    if not attrs_path.is_file():
        return []

    patterns: List[str] = []
    try:
        lines = attrs_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "export-ignore" not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        pattern = parts[0].strip()
        if pattern:
            patterns.append(pattern)
    return patterns


def matches_export_ignore(rel_path: str, patterns: Sequence[str]) -> bool:
    rel = normalize_rel_path(rel_path)
    for pattern in patterns:
        pat = pattern.strip()
        if not pat:
            continue
        anchored = pat.startswith("/")
        pat = normalize_rel_path(pat)
        if pat.endswith("/"):
            prefix = pat
            if rel.startswith(prefix) or rel == prefix.rstrip("/"):
                return True
            continue
        if anchored and rel == pat:
            return True
        if not anchored and (rel == pat or rel.endswith("/" + pat)):
            return True
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def classify_private_path(
    rel_path: str,
    *,
    export_ignore_patterns: Optional[Sequence[str]] = None,
) -> Optional[str]:
    rel = normalize_rel_path(rel_path)
    rel_lower = rel.lower()

    if any(marker in rel_lower for marker in SECRET_PATH_MARKERS):
        return "secret-policy"
    if rel in PRIVATE_EXACT_PATHS:
        return "private-policy"
    if any(rel.startswith(prefix) for prefix in PRIVATE_PREFIXES):
        return "private-policy"
    if export_ignore_patterns and matches_export_ignore(rel, export_ignore_patterns):
        return "export-ignore-policy"
    return None


def is_private_path(
    rel_path: str,
    *,
    export_ignore_patterns: Optional[Sequence[str]] = None,
) -> bool:
    return classify_private_path(rel_path, export_ignore_patterns=export_ignore_patterns) is not None


def resolve_ingest_path(
    path: str,
    root: Path,
    *,
    allow_outside_root: bool = False,
    include_private: bool = False,
    export_ignore_patterns: Optional[Sequence[str]] = None,
) -> Tuple[Optional[Path], FilePolicyDecision]:
    """Resolve a user-supplied ingest path before any adapter reads it."""
    root = Path(root).resolve()
    if allow_outside_root:
        resolved = Path(path).expanduser().resolve()
    else:
        try:
            resolved = confine_to_root(path, root)
        except ValueError as exc:
            return None, FilePolicyDecision(False, str(exc))

    if not resolved.is_file():
        return resolved, FilePolicyDecision(False, "file not found")

    if not include_private:
        try:
            rel = normalize_rel_path(resolved.relative_to(root))
        except ValueError:
            rel = str(resolved)
        reason = classify_private_path(rel, export_ignore_patterns=export_ignore_patterns)
        if reason:
            return resolved, FilePolicyDecision(False, reason)

    return resolved, FilePolicyDecision(True, "")


def unique_existing_files(paths: Iterable[Path]) -> List[Path]:
    seen = set()
    out: List[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        out.append(path)
    return sorted(out)
