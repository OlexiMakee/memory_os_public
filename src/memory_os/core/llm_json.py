"""Deterministic cleanup for JSON returned by language models."""

from __future__ import annotations


def strip_json_code_fence(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    first_newline = cleaned.find("\n")
    if first_newline < 0:
        return cleaned
    body = cleaned[first_newline + 1 :].rstrip()
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()
