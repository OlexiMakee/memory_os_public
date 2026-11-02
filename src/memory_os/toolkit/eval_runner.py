import json
import os
from pathlib import Path
from typing import Any, Dict, List

from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.modules.search import MemorySearcher


EVALS_DIR = Path(__file__).resolve().parent / "evals"
LLM_KEY_ENV_VARS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")
MAX_EVAL_FILE_BYTES = 10 * 1024 * 1024


def _check_expected_args(expected: Dict[str, Any], actual: Dict[str, Any]) -> bool:
    """
    Check that actual args satisfy expected_args spec.

    Each entry in expected can be:
      "key": true         — actual must contain exactly this key
      "label": [a, b, …]  — actual must contain at least one of the listed keys
                            (use for synonym groups, e.g. summary/rule/fact)
    """
    for label, spec in expected.items():
        if isinstance(spec, list):
            if not any(k in actual for k in spec):
                return False
        else:
            if label not in actual:
                return False
    return True


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

        if kind == "agent_action":
            if not self._has_llm_key() and not self._local_ollama_reachable():
                return {
                    "suite": suite_name,
                    "kind": kind,
                    "status": "skipped",
                    "reason": "no LLM API key and no local Ollama reachable",
                    "cases": [],
                    "pass_rate": 0.0,
                    "pass_threshold": pass_threshold,
                    "ok": True,
                }
            return self._run_agent_action(suite_name, kind, pass_threshold, cases)

        if kind == "responder_quality":
            if not self._has_llm_key() and not self._local_ollama_reachable():
                return {
                    "suite": suite_name,
                    "kind": kind,
                    "status": "skipped",
                    "reason": "no LLM API key and no local Ollama reachable",
                    "cases": [],
                    "pass_rate": 0.0,
                    "pass_threshold": pass_threshold,
                    "ok": True,
                }
            return self._run_responder_quality(suite_name, kind, pass_threshold, cases)

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
        searcher = MemorySearcher(
            self.config,
            repository=MemoryRepository(FileSystemMemoryStorage(), self.config, indexer=MemoryOS(self.config)),
        )
        case_results = []
        top_k = 5

        for case in cases:
            case_id = case.get("id", "")
            query = case.get("query", "")
            expected = self._retrieval_expected_substrings(case)
            absent = str(case.get("expect_absent_substring", "")).strip().lower()

            if not query or (not expected and not absent):
                case_results.append({
                    "id": case_id,
                    "passed": False,
                    "detail": "missing query and expected retrieval assertion",
                })
                continue

            try:
                results = searcher.search_memory(query, depth=0)[:top_k]
            except Exception as exc:
                case_results.append({
                    "id": case_id,
                    "passed": False,
                    "detail": f"search failed: {exc}",
                })
                continue

            relevant_count = sum(1 for result in results if self._retrieval_result_matches(result, expected))
            positive_matched = bool(expected) and relevant_count > 0
            absent_matched = bool(absent) and any(self._retrieval_result_matches(result, [absent]) for result in results)
            positive_ok = positive_matched if expected else True
            absent_ok = not absent_matched if absent else True
            matched = positive_ok and absent_ok
            # Standard precision@k: relevant / returned, not relevant / k.
            # Dividing by the fixed top_k regardless of how many results came
            # back structurally caps precision at 1/5=0.2 for single-answer
            # factual queries (the common case here) even when the search
            # returns exactly the one correct node and nothing else --
            # that's perfect precision, not 20% precision.
            precision_at_5 = (relevant_count / len(results)) if (expected and results) else (0.0 if expected else None)
            recall_at_5 = 1.0 if positive_matched else (0.0 if expected else None)

            case_results.append({
                "id": case_id,
                "passed": matched,
                "detail": self._retrieval_case_detail(expected, absent, positive_matched, absent_matched, top_k),
                "recall_at_5": recall_at_5,
                "precision_at_5": precision_at_5,
                "expected_any": expected,
                "expect_absent_substring": absent,
            })

        pass_rate = self._pass_rate(case_results)
        positive_results = [case for case in case_results if case.get("recall_at_5") is not None]
        recall_at_5 = (
            sum(float(case.get("recall_at_5", 0.0)) for case in positive_results) / len(positive_results)
            if positive_results else 0.0
        )
        precision_at_5 = (
            sum(float(case.get("precision_at_5", 0.0)) for case in positive_results) / len(positive_results)
            if positive_results else 0.0
        )
        return {
            "suite": suite_name,
            "kind": kind,
            "status": "ok",
            "cases": case_results,
            "metric": f"recall@{top_k}/precision@{top_k}",
            "recall_at_5": recall_at_5,
            "precision_at_5": precision_at_5,
            "pass_rate": pass_rate,
            "pass_threshold": pass_threshold,
            "ok": pass_rate >= pass_threshold,
        }

    def _retrieval_expected_substrings(self, case: Dict[str, Any]) -> List[str]:
        expected_any = case.get("expected_any")
        expected: List[str] = []
        if isinstance(expected_any, list):
            expected.extend(str(item).strip().lower() for item in expected_any if str(item).strip())
        legacy = str(case.get("expected_node_id_substring", "")).strip().lower()
        if legacy:
            expected.append(legacy)
        return list(dict.fromkeys(expected))

    @staticmethod
    def _retrieval_result_matches(result: Dict[str, Any], expected: List[str]) -> bool:
        if not expected:
            return False
        text = " ".join([
            str(result.get("id", "")),
            str(result.get("summary", "")),
        ]).lower()
        return any(item in text for item in expected)

    @staticmethod
    def _retrieval_case_detail(
        expected: List[str],
        absent: str,
        positive_matched: bool,
        absent_matched: bool,
        top_k: int,
    ) -> str:
        parts = []
        if expected:
            parts.append(
                f"matched one of {expected!r}"
                if positive_matched
                else f"expected one of {expected!r} not found in top {top_k} results"
            )
        if absent:
            parts.append(
                f"absent substring {absent!r} not found in top {top_k} results"
                if not absent_matched
                else f"absent substring {absent!r} unexpectedly found in top {top_k} results"
            )
        return "; ".join(parts)

    def _run_agent_action(
        self,
        suite_name: str,
        kind: str,
        pass_threshold: float,
        cases: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        The eval gate the candidate-LoRA promote/reject loop depends on
        (see lora/registry.py AdapterRegistry.promote/reject): does the
        currently configured ActionBrain pick the right action and return
        parseable JSON for each fixture task? Today this exercises whatever
        local-first provider is configured (no trained action-LoRA yet);
        once one exists, point its Ollama tag at --model and re-run the
        same suite to compare against a baseline result via 'eval compare'.
        """
        from memory_os.agent_brain.brain import LocalLLMActionBrain
        from memory_os.agent_brain.vocabulary import default_memory_os_vocabulary

        brain = LocalLLMActionBrain()
        vocabulary = default_memory_os_vocabulary()
        case_results = []

        for case in cases:
            case_id = case.get("id", "")
            task = case.get("task", "")
            expected_action = case.get("expected_action", "")

            try:
                request = brain.propose_action(task, vocabulary)
            except Exception as exc:
                case_results.append({
                    "id": case_id,
                    "passed": False,
                    "detail": f"propose_action failed: {exc}",
                })
                continue

            passed = request.action == expected_action
            if "expected_args" in case:
                passed = passed and _check_expected_args(case["expected_args"], request.args or {})
            case_results.append({
                "id": case_id,
                "passed": passed,
                "detail": f"got action {request.action!r}, expected {expected_action!r}",
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

    def _run_responder_quality(
        self,
        suite_name: str,
        kind: str,
        pass_threshold: float,
        cases: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Checks that LocalLLMResponder generates non-empty Ukrainian responses.

        Each case must provide: task, action, result_data (str or null), result_ok (bool).
        Optional: result_error (str). The responder is called with a mock ActionResult
        and the response is checked for basic Ukrainian language quality signals.
        """
        import re

        from memory_os.agent_brain.responder import LocalLLMResponder
        from memory_os.agent_brain.types import ActionResult
        from memory_os.lora.dataset import UK_RESPONDER_SYSTEM_PROMPT

        _CYRILLIC = re.compile(r"[Ѐ-ӿ]")
        _ERROR_PREFIXES = ("Traceback ", "Error:", "AttributeError", "Exception")

        responder = LocalLLMResponder(system_prompt=UK_RESPONDER_SYSTEM_PROMPT)
        case_results = []

        for case in cases:
            case_id = case.get("id", "")
            task = case.get("task", "")
            action = case.get("action", "chat")
            result_ok = bool(case.get("result_ok", True))
            result_data = case.get("result_data") or ""
            result_error = case.get("result_error") or ""

            mock_result = ActionResult(
                action=action,
                ok=result_ok,
                data=result_data if result_ok else None,
                error=result_error if not result_ok else None,
            )

            try:
                response = responder.respond(task, mock_result)
            except Exception as exc:
                case_results.append({
                    "id": case_id,
                    "passed": False,
                    "detail": f"responder raised: {exc}",
                })
                continue

            if not response or not response.strip():
                case_results.append({"id": case_id, "passed": False, "detail": "empty response"})
                continue
            if len(response.strip()) < 10:
                case_results.append({"id": case_id, "passed": False, "detail": f"response too short ({len(response)} chars)"})
                continue
            if len(response.strip()) > 800:
                case_results.append({"id": case_id, "passed": False, "detail": f"response too long ({len(response)} chars)"})
                continue
            if response.startswith(_ERROR_PREFIXES):
                case_results.append({"id": case_id, "passed": False, "detail": "response looks like an error/traceback"})
                continue
            cyrillic_count = len(_CYRILLIC.findall(response))
            if cyrillic_count < 3:
                case_results.append({"id": case_id, "passed": False, "detail": f"too few Cyrillic chars ({cyrillic_count})"})
                continue
            case_results.append({"id": case_id, "passed": True, "detail": f"ok, {len(response)} chars, {cyrillic_count} Cyrillic"})

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

    def _local_ollama_reachable(self) -> bool:
        import os

        from memory_os.core.llm_service import _discover_ollama_model

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        return _discover_ollama_model(host) is not None

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
