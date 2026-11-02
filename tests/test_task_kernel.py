import json
from datetime import datetime

import pytest

from memory_os.toolkit.task_kernel import TaskKernel


def test_create_returns_pending_task_with_core_fields(tmp_path):
    kernel = TaskKernel(tmp_path)

    task = kernel.create("Write tests", goal="Cover TaskKernel", risk="medium")

    assert task["id"].startswith("task_")
    assert task["title"] == "Write tests"
    assert task["status"] == "pending"
    assert task["created_at"]
    datetime.fromisoformat(task["created_at"])
    assert task["updated_at"] == task["created_at"]
    assert task["agent"] is None
    assert kernel.get(task["id"]) == task


def test_list_tasks_filters_by_status_agent_and_risk(tmp_path):
    kernel = TaskKernel(tmp_path)
    low_task = kernel.create("Low risk", risk="low")
    high_task = kernel.create("High risk", risk="high")
    blocked_task = kernel.create("Blocked task", risk="medium")

    kernel.claim(high_task["id"], "agent-alpha")
    kernel.claim(blocked_task["id"], "agent-beta")
    kernel.block(blocked_task["id"], "Waiting on input")

    assert [task["id"] for task in kernel.list_tasks(status="pending")] == [low_task["id"]]
    assert [task["id"] for task in kernel.list_tasks(status="claimed")] == [high_task["id"]]
    assert [task["id"] for task in kernel.list_tasks(status="blocked")] == [blocked_task["id"]]
    assert [task["id"] for task in kernel.list_tasks(agent="agent-alpha")] == [high_task["id"]]
    assert [task["id"] for task in kernel.list_tasks(risk="high")] == [high_task["id"]]
    assert [task["id"] for task in kernel.list_tasks(agent="agent-beta", risk="medium")] == [
        blocked_task["id"]
    ]


def test_full_happy_path_create_claim_start_done(tmp_path):
    kernel = TaskKernel(tmp_path)
    task = kernel.create("Ship feature")

    claimed = kernel.claim(task["id"], "agent-alpha", lease_minutes=15)
    assert claimed["status"] == "claimed"
    assert claimed["agent"] == "agent-alpha"
    assert claimed["lease_owner"] == "agent-alpha"
    assert claimed["lease_expires"]

    leases = json.loads(kernel.leases_path.read_text(encoding="utf-8"))
    assert leases[task["id"]]["owner"] == "agent-alpha"
    assert leases[task["id"]]["expires"] == claimed["lease_expires"]

    running = kernel.start(task["id"])
    assert running["status"] == "running"

    done = kernel.done(task["id"], "Implemented and verified")
    assert done["status"] == "done"
    assert done["handoff_summary"] == "Implemented and verified"
    assert task["id"] not in json.loads(kernel.leases_path.read_text(encoding="utf-8"))


def test_block_flow_claim_again_start_done(tmp_path):
    kernel = TaskKernel(tmp_path)
    task = kernel.create("Handle dependency")

    kernel.claim(task["id"], "agent-alpha")
    blocked = kernel.block(task["id"], "Need clarification")
    assert blocked["status"] == "blocked"
    assert blocked["blocked_reason"] == "Need clarification"

    reclaimed = kernel.claim(task["id"], "agent-beta")
    assert reclaimed["status"] == "claimed"
    assert reclaimed["agent"] == "agent-beta"

    running = kernel.start(task["id"])
    assert running["status"] == "running"

    done = kernel.done(task["id"], "Clarified and completed")
    assert done["status"] == "done"
    assert done["handoff_summary"] == "Clarified and completed"


def test_review_flow_create_claim_start_review_done(tmp_path):
    kernel = TaskKernel(tmp_path)
    task = kernel.create("Needs review")

    kernel.claim(task["id"], "agent-alpha")
    kernel.start(task["id"])
    in_review = kernel.review(task["id"], "Ready for review")

    assert in_review["status"] == "review"
    assert in_review["handoff_summary"] == "Ready for review"

    done = kernel.done(task["id"], "Review passed")
    assert done["status"] == "done"
    assert done["handoff_summary"] == "Review passed"


def test_unclaim_returns_task_to_pending_and_removes_agent_and_lease(tmp_path):
    kernel = TaskKernel(tmp_path)
    task = kernel.create("Release me")
    kernel.claim(task["id"], "agent-alpha")

    unclaimed = kernel.unclaim(task["id"])

    assert unclaimed["status"] == "pending"
    assert unclaimed["agent"] is None
    assert unclaimed["lease_owner"] is None
    assert unclaimed["lease_expires"] is None
    assert task["id"] not in json.loads(kernel.leases_path.read_text(encoding="utf-8"))


def test_stale_leases_returns_expired_leases(tmp_path):
    kernel = TaskKernel(tmp_path)
    expired_task = kernel.create("Expired lease")
    active_task = kernel.create("Active lease")
    expired = kernel.claim(expired_task["id"], "agent-old", lease_minutes=-1)
    active = kernel.claim(active_task["id"], "agent-current", lease_minutes=30)

    stale = kernel.stale_leases()

    assert stale == [
        {
            "task_id": expired_task["id"],
            "owner": "agent-old",
            "expires": expired["lease_expires"],
        }
    ]
    assert active["lease_expires"] not in {lease["expires"] for lease in stale}


def test_release_stale_leases_unclaims_claimed_and_blocks_running(tmp_path):
    kernel = TaskKernel(tmp_path)
    claimed_task = kernel.create("Claimed stale")
    running_task = kernel.create("Running stale")
    fresh_task = kernel.create("Fresh")

    kernel.claim(claimed_task["id"], "agent-old", lease_minutes=-1)
    kernel.claim(running_task["id"], "agent-old", lease_minutes=-1)
    kernel.start(running_task["id"])
    kernel.claim(fresh_task["id"], "agent-new", lease_minutes=30)

    healed = kernel.release_stale_leases()

    assert {item["task_id"] for item in healed} == {claimed_task["id"], running_task["id"]}
    assert kernel.get(claimed_task["id"])["status"] == "pending"
    assert kernel.get(running_task["id"])["status"] == "blocked"
    assert "lease expired" in kernel.get(running_task["id"])["blocked_reason"]
    assert kernel.get(fresh_task["id"])["status"] == "claimed"


def test_events_log_records_transitions_and_honors_limit(tmp_path):
    kernel = TaskKernel(tmp_path)
    task = kernel.create("Emit events")

    kernel.claim(task["id"], "agent-alpha")
    kernel.start(task["id"])
    kernel.block(task["id"], "Paused")
    kernel.claim(task["id"], "agent-alpha")
    kernel.start(task["id"])
    kernel.review(task["id"], "Ready")
    kernel.done(task["id"], "Complete")

    events = kernel.events(task["id"])
    assert [event["event"] for event in events] == [
        "created",
        "claimed",
        "started",
        "blocked",
        "claimed",
        "started",
        "review",
        "done",
    ]
    assert all(event["task_id"] == task["id"] for event in events)
    assert all(event["ts"] for event in events)
    assert events[1]["agent"] == "agent-alpha"
    assert events[3]["reason"] == "Paused"
    assert [event["event"] for event in kernel.events(task["id"], limit=3)] == [
        "started",
        "review",
        "done",
    ]


def test_error_cases_for_missing_task_and_invalid_start_state(tmp_path):
    kernel = TaskKernel(tmp_path)

    with pytest.raises(KeyError, match="Task not found"):
        kernel.claim("task_missing", "agent-alpha")

    task = kernel.create("Not claimed yet")
    with pytest.raises(ValueError, match="Cannot start task in status 'pending'"):
        kernel.start(task["id"])


def test_expire_stale_closes_only_old_chat_tasks(tmp_path):
    from datetime import timedelta, timezone
    kernel = TaskKernel(tmp_path)
    old_chat = kernel.create("telegram:claude: що там")
    fresh_chat = kernel.create("telegram:codex: тест")
    old_work = kernel.create("Integrate Task Kernel into UI")

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    for task_id in (old_chat["id"], old_work["id"]):
        task = kernel._load_task(task_id)
        task["updated_at"] = stale_ts
        kernel._append_task(task)

    expired = kernel.expire_stale(hours=24.0)
    expired_ids = {t["id"] for t in expired}

    assert expired_ids == {old_chat["id"]}
    assert kernel.get(old_chat["id"])["status"] == "done"
    assert "auto-expired" in kernel.get(old_chat["id"])["handoff_summary"]
    assert kernel.get(fresh_chat["id"])["status"] == "pending"
    assert kernel.get(old_work["id"])["status"] == "pending"
