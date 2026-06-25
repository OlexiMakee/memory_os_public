"""Optional pydantic-ai availability gate plus contract shape validation."""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List


def is_available() -> bool:
    """Return whether the named pydantic-ai integration is installed."""
    return importlib.util.find_spec("pydantic_ai") is not None


def validate_contract(contract: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the plain contract-builder dictionary shape without mutating it."""
    if not is_available():
        return {"ok": False, "detail": "pydantic_ai package not installed", "errors": []}

    try:
        try:
            from pydantic import BaseModel, ValidationError
            try:
                from pydantic import ConfigDict
            except ImportError:
                ConfigDict = None
        except ImportError:
            return {"ok": False, "detail": "pydantic_ai package not installed", "errors": []}

        class Contract(BaseModel):
            if ConfigDict is not None:
                model_config = ConfigDict(extra="forbid")
            else:
                class Config:
                    extra = "forbid"

            feature_id: str
            title: str
            risk_class: str
            objective: str
            non_goals: List[str]
            inputs_and_outputs: List[str]
            constraints: List[str]
            acceptance_criteria: List[str]
            required_verification: str
            required_context_sources: List[str]
            rollback_plan: str

        try:
            Contract(**contract)
        except ValidationError as exc:
            try:
                errors = [str(error) for error in exc.errors()]
            except Exception:
                errors = [str(exc)]
            return {"ok": False, "detail": "validation failed", "errors": errors}

        return {"ok": True, "detail": "validated", "errors": []}
    except Exception as exc:
        return {"ok": False, "detail": f"validation bridge failed: {exc}", "errors": []}


def audit() -> Dict[str, Any]:
    """Report adapter availability without importing optional packages."""
    return {"available": is_available()}
