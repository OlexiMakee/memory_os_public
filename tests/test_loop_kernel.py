import pytest

from memory_os.toolkit.loop_kernel import LoopKernel, LoopPolicy


def test_loop_attempt_pass_decision(tmp_path):
    loop = LoopKernel(tmp_path)
    attempt = loop.start_attempt("task_abc123", "codex", runtime="file")

    loop.record_verifier(
        "task_abc123",
        attempt["attempt_id"],
        verifier="pytest",
        verdict="pass",
        feedback="121 passed",
    )

    decision = loop.decision("task_abc123")
    assert decision["action"] == "complete"
    attempts = loop.attempts("task_abc123")
    assert attempts[0]["status"] == "passed"
    assert attempts[0]["feedback"] == "121 passed"


def test_loop_failed_attempt_requests_failover(tmp_path):
    loop = LoopKernel(tmp_path)
    attempt = loop.start_attempt("task_abc123", "claude", runtime="tmux")

    loop.record_verifier(
        "task_abc123",
        attempt["attempt_id"],
        verifier="pytest",
        verdict="fail",
        feedback="test failure",
    )

    decision = loop.decision("task_abc123")
    assert decision["action"] == "failover"
    assert decision["attempts"] == 1


def test_loop_retry_budget_exhaustion(tmp_path):
    loop = LoopKernel(tmp_path, policy=LoopPolicy(max_attempts=1))
    attempt = loop.start_attempt("task_abc123", "agy")
    loop.abandon_attempt("task_abc123", attempt["attempt_id"], "rate limited")

    with pytest.raises(RuntimeError, match="retry budget exhausted"):
        loop.start_attempt("task_abc123", "codex")

    decision = loop.decision("task_abc123")
    assert decision["action"] == "stop"
