import json
import os
from pathlib import Path
from typing import Any, Dict, List

from memory_os.core.config import MemoryOSConfig
from memory_os.modules.search import MemorySearcher


EVALS_DIR = Path(__file__).resolve().parent / "evals"
LLM_KEY_ENV_VARS = ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")
MAX_EVAL_FILE_BYTES = 10 * 1024 * 1024


class EvalRunner:
    """Runs deterministic local evals and optional LLM-judged eval suites."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def list_suites(self) -> List[Dict[str, Any]]:
        suites = []
        if not EVALS_DIR.exists():
            return suites

        for suite_dir in sorted(path for path in EVALS_DIR.iterdir() if path.is_dir()):
            if not self._is_under_evals_dir(suite_dir):
                continue
            try:
                suite_config = self._load_suite_config(suite_dir)
                case_count = len(self._load_cases(suite_dir))
            except Exception:
                continue

            suites.append({
                "name": suite_dir.name,
                "kind": suite_config.get("kind", ""),
                "pass_threshold": self._normalize_threshold(
                    suite_config.get("pass_threshold", 1.0)
                ),
                "case_count": case_count,
                "description": suite_config.get("description", ""),
            })
        return suites

    def run(self, suite_name: str) -> Dict[str, Any]:
        suite_dir = EVALS_DIR / suite_name
        if not self._is_under_evals_dir(suite_dir) or not suite_dir.is_dir():
            return self._error_result(suite_name, "", 1.0, f"suite not found: {suite_name}")

        try:
            suite_config = self._load_suite_config(suite_dir)
            cases = self._load_cases(suite_dir)
        except Exception as exc:
            return self._error_result(suite_name, "", 1.0, f"failed to load suite: {exc}")

        kind = suite_config.get("kind", "")
        pass_threshold = self._normalize_threshold(suite_config.get("pass_threshold", 1.0))

        if kind == "local":
            if suite_name == "retrieval-relevance":
                return self._run_retrieval_relevance(suite_name, kind, pass_threshold, cases)
            return self._error_result(
                suite_name,
                kind,
                pass_threshold,
                f"unsupported local suite: {suite_name}",
            )

        if kind == "llm_judge":
            if not self._has_llm_key():
                return {
                    "suite": suite_name,
                    "kind": kind,
                    "status": "skipped",
                    "reason": "no LLM API key configured",
                    "cases": [],
                    "pass_rate": 0.0,
                    "pass_threshold": pass_threshold,
                    "ok": True,
                }
            return {
                "suite": suite_name,
                "kind": kind,
                "status": "skipped",
                "reason": "LLM judge execution is not implemented",
                "cases": [],
                "pass_rate": 0.0,
                "pass_threshold": pass_threshold,
                "ok": True,
            }

        return self._error_result(suite_name, kind, pass_threshold, f"unsupported suite kind: {kind}")

    def compare(self, baseline: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        baseline_cases = {
            case.get("id"): bool(case.get("passed"))
            for case in baseline.get("cases", [])
            if case.get("id") is not None
        }
        candidate_cases = {
            case.get("id"): bool(case.get("passed"))
            for case in candidate.get("cases", [])
            if case.get("id") is not None
        }

        flipped = []
        for case_id in sorted(set(baseline_cases) | set(candidate_cases)):
            before = baseline_cases.get(case_id)
            after = candidate_cases.get(case_id)
            if before != after:
                flipped.append({
                    "id": case_id,
                    "baseline_passed": before,
                    "candidate_passed": after,
                })

        return {
            "baseline_suite": baseline.get("suite"),
            "candidate_suite": candidate.get("suite"),
            "pass_rate_delta": (
                float(candidate.get("pass_rate", 0.0)) -
                float(baseline.get("pass_rate", 0.0))
            ),
            "flipped_cases": flipped,
        }

    def _run_retrieval_relevance(
        self,
        suite_name: str,
        kind: str,
        pass_threshold: float,
        cases: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        searcher = MemorySearcher(self.config)
        case_results = []

        for case in cases:
            case_id = case.get("id", "")
            query = case.get("query", "")
            expected = str(case.get("expected_node_id_substring", "")).lower()

            if not query or not expected:
                case_results.append({
                    "id": case_id,
                    "passed": False,
                    "detail": "missing query or expected_node_id_substring",
                })
                continue

            try:
                results = searcher.search_memory(query)
            except Exception as exc:
                case_results.append({
                    "id": case_id,
                    "passed": False,
                    "detail": f"search failed: {exc}",
                })
                continue

            matched = False
            for result in results:
                node_id = str(result.get("id", "")).lower()
                summary = str(result.get("summary", "")).lower()
                if expected in node_id or expected in summary:
                    matched = True
                    break

            case_results.append({
                "id": case_id,
                "passed": matched,
                "detail": (
                    f"matched expected substring {expected!r}"
                    if matched
                    else f"expected substring {expected!r} not found in {len(results)} results"
                ),
            })

        pass_rate = self._pass_rate(case_results)
        return {
            "suite": suite_name,
            "kind": kind,
            "status": "ok",
            "cases": case_results,
            "pass_rate": pass_rate,
            "pass_threshold": pass_threshold,
            "ok": pass_rate >= pass_threshold,
        }

    def _load_suite_config(self, suite_dir: Path) -> Dict[str, Any]:
        path = suite_dir / "config.json"
        self._check_eval_file_size(path)
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _load_cases(self, suite_dir: Path) -> List[Dict[str, Any]]:
        cases = []
        path = suite_dir / "cases.jsonl"
        self._check_eval_file_size(path)
        with path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                case = json.loads(stripped)
                if "id" not in case:
                    raise ValueError(f"case on line {line_number} is missing id")
                cases.append(case)
        return cases

    def _is_under_evals_dir(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(EVALS_DIR.resolve())
        except (OSError, ValueError):
            return False
        return True

    def _check_eval_file_size(self, path: Path) -> None:
        if path.stat().st_size > MAX_EVAL_FILE_BYTES:
            raise ValueError(f"{path.name} exceeds {MAX_EVAL_FILE_BYTES} byte limit")

    def _normalize_threshold(self, value: Any) -> float:
        threshold = float(value)
        if threshold < 0.0 or threshold > 1.0:
            raise ValueError(f"pass_threshold must be between 0 and 1, got {threshold}")
        return threshold

    def _has_llm_key(self) -> bool:
        return any(os.environ.get(name) for name in LLM_KEY_ENV_VARS)

    def _pass_rate(self, cases: List[Dict[str, Any]]) -> float:
        if not cases:
            return 0.0
        passed = sum(1 for case in cases if case.get("passed"))
        return passed / len(cases)

    def _error_result(
        self,
        suite_name: str,
        kind: str,
        pass_threshold: float,
        detail: str,
    ) -> Dict[str, Any]:
        return {
            "suite": suite_name,
            "kind": kind,
            "status": "error",
            "cases": [],
            "pass_rate": 0.0,
            "pass_threshold": pass_threshold,
            "ok": False,
            "error": detail,
        }
