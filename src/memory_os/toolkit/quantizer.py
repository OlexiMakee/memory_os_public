#!/usr/bin/env python3
import sys
import json
import argparse
from typing import Dict, Any, List, Tuple


LEVEL_SCALE = {
    0: "L0",
    1: "L1",
    2: "L2",
    3: "L3",
    4: "L4",
    5: "L5",
    6: "L6",
    7: "L7",
    8: "L8",
    9: "L9",
    10: "L10",
    11: "L11",
    12: "L12",
    13: "L13",
}

LEGACY_BANDS: List[Tuple[int, int, int]] = [
    (1, 10, 1),
    (11, 18, 2),
    (19, 25, 3),
    (26, 33, 4),
    (34, 40, 5),
    (41, 48, 6),
    (49, 56, 7),
    (57, 64, 8),
    (65, 75, 9),
    (76, 82, 10),
    (83, 90, 11),
    (91, 100, 12),
]

def calculate_score(task_desc: str, risk: float = 0.0, volume: float = 0.0, uncertainty: float = 0.0) -> int:
    """Return legacy 1-100 complexity score for compatibility."""
    # Base score
    score = 10.0
    
    desc_lower = task_desc.lower()
    
    # 1. Analyze keywords
    if any(k in desc_lower for k in ["migration", "schema", "db", "database", "sql", "table"]):
        score += 35.0
    if any(k in desc_lower for k in ["refactor", "solid", "srp", "ocp", "architecture"]):
        score += 25.0
    if any(k in desc_lower for k in ["credential", "encrypt", "secret", "password", "key"]):
        score += 25.0
    if any(k in desc_lower for k in ["test", "unittest", "compile"]):
        score += 5.0
    if any(k in desc_lower for k in ["typo", "todo", "fix comment", "rename tab"]):
        score -= 5.0
        
    # 2. Add factors
    score += risk * 40.0
    score += volume * 20.0
    score += uncertainty * 15.0
    
    # Clamp
    final_score = int(round(score))
    return max(1, min(100, final_score))


def legacy_score_to_level(score: int) -> int:
    """Map legacy 1-100 complexity score to the new L1-L12 bands."""
    score = max(1, min(100, int(score)))
    for lower, upper, level in LEGACY_BANDS:
        if lower <= score <= upper:
            return level
    return 12


def calculate_level(
    task_desc: str,
    risk: float = 0.0,
    volume: float = 0.0,
    uncertainty: float = 0.0,
) -> int:
    """Return L0-L13 Memory OS level."""
    if uncertainty > 0.9:
        return 13
    if risk == 0.0 and volume == 0.0 and uncertainty == 0.0 and any(k in task_desc.lower() for k in ["lint", "format", "syntax"]):
        return 0
    return legacy_score_to_level(calculate_score(task_desc, risk, volume, uncertainty))


def _workflow_for_level(level: int, task_desc: str = "") -> str:
    if level == 0:
        return "deterministic.l0"
    if level <= 4:
        return "bounded.l1_l4"
    if level <= 11:
        return "progressive.l5_l11"
    if level == 12:
        return "unlimited.l12"
    return "external.l13"


def _model_policy_for_level(level: int) -> str:
    if level == 0:
        return "none"
    if level <= 4:
        return "cheap_free"
    if level <= 8:
        return "codex"
    if level <= 11:
        return "strong_cloud"
    return "large_reasoning"


def resolve_profile(score: int, uncertainty: float = 0.0, task_desc: str = "") -> Dict[str, Any]:
    """Resolve a legacy score or level to a profile."""
    if 0 <= score <= 13:
        level = score
        legacy_score = None
    else:
        legacy_score = max(1, min(100, int(score)))
        level = legacy_score_to_level(legacy_score)
        
    if uncertainty > 0.9:
        level = 13

    level_name = LEVEL_SCALE[level]
    escalate = level >= 12
    result = {
        "profile": level_name,
        "level": level,
        "level_name": level_name,
        "model_policy": _model_policy_for_level(level),
        "workflow_id": _workflow_for_level(level, task_desc),
        "escalate": escalate,
    }
    if legacy_score is not None:
        result["legacy_score"] = legacy_score
    if level == 13:
        result["escalate_reason"] = "Protocol 13 engaged: You are operating outside of Memory OS. Do NOT consult nodes, edges, or events. Analyze the target codebase strictly from the outside."
    elif escalate:
        result["escalate_reason"] = "Task requires Unlimited Context (L12)."
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description="Quantize task complexity and resolve Memory OS workflow profiles.")
    parser.add_argument("--task", required=True, help="Task description string.")
    parser.add_argument("--risk", type=float, default=0.0, help="Risk factor (0.0 to 1.0).")
    parser.add_argument("--volume", type=float, default=0.0, help="Data volume factor (0.0 to 1.0).")
    parser.add_argument("--uncertainty", type=float, default=0.0, help="Uncertainty factor (0.0 to 1.0).")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of human-readable text.")
    args = parser.parse_args()
    
    legacy_score = calculate_score(args.task, args.risk, args.volume, args.uncertainty)
    profile_info = resolve_profile(legacy_score, args.uncertainty, args.task)
    
    result = {
        "task": args.task,
        "legacy_score": legacy_score,
        **profile_info
    }
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Task: {result['task']}")
        print(f"Legacy Score: {result['legacy_score']}/100")
        print(f"Level: {result['level']}/13")
        print(f"Level Name: {result['level_name']}")
        print(f"Model Policy: {result['model_policy']}")
        print(f"Workflow ID: {result['workflow_id']}")
        if result["escalate"]:
            print(f"ESCALATION REQUIRED: {result.get('escalate_reason', 'Threshold exceeded.')}")
            
    return 0

if __name__ == "__main__":
    sys.exit(main())
