#!/usr/bin/env python3
"""Adapter for the markitdown library to ingest external document formats into Markdown."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

from memory_os.core.safe_id import confine_to_root


def is_available() -> bool:
    """Check if the markitdown library is available in the environment."""
    return importlib.util.find_spec("markitdown") is not None


class MarkItDownAdapter:
    """Document ingestion adapter wrapper around markitdown."""

    def __init__(self) -> None:
        pass

    def convert(
        self,
        path: str,
        dry_run: bool = True,
        allowed_root: Optional[Union[str, Path]] = None,
        allow_outside_root: bool = False,
    ) -> Dict[str, Any]:
        """Convert a local file to Markdown.

        Validates that the file exists, computes the SHA-256 hash of the content,
        and uses markitdown to convert the content to Markdown text.
        """
        try:
            if allowed_root is not None and not allow_outside_root:
                path = str(confine_to_root(path, Path(allowed_root)))
            return self._convert(path, dry_run)
        except Exception as e:
            # Catches argument-validation errors (e.g. a non-string path raising
            # TypeError from os.path.isfile) that the inner try/excepts below
            # don't cover, so this adapter never raises out to its caller.
            return {"ok": False, "detail": f"unexpected error: {e}"}

    def _convert(self, path: str, dry_run: bool) -> Dict[str, Any]:
        # Validate that the path exists and is a file
        if not os.path.isfile(path):
            return {"ok": False, "detail": "file not found"}

        # Compute SHA-256 of the raw file bytes
        try:
            with open(path, "rb") as f:
                content = f.read()
        except Exception as e:
            return {"ok": False, "detail": f"failed to read file: {e}"}

        sha256_hash = hashlib.sha256(content).hexdigest()
        size_bytes = len(content)
        original_filename = os.path.basename(path)
        original_suffix = os.path.splitext(path)[1]

        # Check if the markitdown package is installed
        if not is_available():
            return {
                "ok": False,
                "detail": "markitdown package not installed",
                "source_path": path,
                "source_filename": original_filename,
                "source_suffix": original_suffix,
                "source_sha256": sha256_hash,
                "source_bytes": size_bytes,
            }

        # Lazy import of markitdown
        try:
            from markitdown import MarkItDown
        except ImportError as e:
            return {
                "ok": False,
                "detail": f"markitdown package not installed: {e}",
                "source_path": path,
                "source_filename": original_filename,
                "source_suffix": original_suffix,
                "source_sha256": sha256_hash,
                "source_bytes": size_bytes,
            }

        # Safe conversion under a broad try/except block
        try:
            # Safest default mode: do not pass any LLM clients or external scripting config
            md = MarkItDown()
            result = md.convert(path)
            if result is None:
                raise ValueError("conversion returned a None result")
            
            markdown_text = result.text_content
            if markdown_text is None:
                markdown_text = ""
        except Exception as e:
            return {
                "ok": False,
                "detail": f"conversion failed: {e}",
                "source_path": path,
                "source_filename": original_filename,
                "source_suffix": original_suffix,
                "source_sha256": sha256_hash,
                "source_bytes": size_bytes,
            }

        return {
            "ok": True,
            "source_path": path,
            "source_filename": original_filename,
            "source_suffix": original_suffix,
            "source_sha256": sha256_hash,
            "source_bytes": size_bytes,
            "markdown_text": markdown_text,
            "dry_run": dry_run,
        }

    def audit(self) -> Dict[str, Any]:
        """Audit the availability of the adapter."""
        return {"available": is_available()}
