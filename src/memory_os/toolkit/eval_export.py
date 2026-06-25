import json
from pathlib import Path
from typing import Any, Dict, List, Optional


EVALS_DIR = Path(__file__).resolve().parent / "evals"
DEFAULT_EXPORTS_DIR = Path("agent_context") / "eval_exports"


def export_suite(
    suite_name: str,
    target: str,
    evals_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Export a native Memory OS eval suite to a best-effort config shape."""
    if target not in {"inspect", "promptfoo"}:
        raise ValueError(f"unsupported eval export target: {target}")

    suite_dir = _suite_dir(suite_name, evals_dir)
    suite_config = _load_suite_config(suite_dir)
    cases = _load_cases(suite_dir)

    if target == "inspect":
        return _export_inspect(suite_name, cases)
    return _export_promptfoo(suite_config, cases)


def write_export(
    suite_name: str,
    target: str,
    out_path: Optional[str] = None,
    evals_dir: Optional[Path] = None,
) -> Path:
    """Write an exported eval config as indented JSON and return its path."""
    exported = export_suite(suite_name, target, evals_dir=evals_dir)
    destination = Path(out_path) if out_path else DEFAULT_EXPORTS_DIR / f"{suite_name}.{target}.json"
    if not _is_under_base_dir(destination, DEFAULT_EXPORTS_DIR):
        raise ValueError(f"export path outside exports directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as f:
        json.dump(exported, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return destination


def _suite_dir(suite_name: str, evals_dir: Optional[Path]) -> Path:
    base_dir = evals_dir if evals_dir is not None else EVALS_DIR
    suite_dir = base_dir / suite_name
    if not _is_under_base_dir(suite_dir, base_dir) or not suite_dir.is_dir():
        raise FileNotFoundError(f"suite not found: {suite_name}")
    return suite_dir


def _is_under_base_dir(path: Path, base_dir: Path) -> bool:
    try:
        path.resolve().relative_to(base_dir.resolve())
    except (OSError, ValueError):
        return False
    return True


def _load_suite_config(suite_dir: Path) -> Dict[str, Any]:
    with (suite_dir / "config.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_cases(suite_dir: Path) -> List[Dict[str, Any]]:
    cases = []
    with (suite_dir / "cases.jsonl").open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                cases.append(json.loads(stripped))
    return cases


def _export_inspect(suite_name: str, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "name": suite_name,
        "dataset": [
            {
                "input": case.get("query") or case.get("source_text") or case,
                "target": case.get("expected_node_id_substring") or case.get("summary") or "",
            }
            for case in cases
        ],
    }


def _export_promptfoo(suite_config: Dict[str, Any], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "description": suite_config.get("description", ""),
        "tests": [
            {
                "vars": case,
                "assert": [],
            }
            for case in cases
        ],
    }
