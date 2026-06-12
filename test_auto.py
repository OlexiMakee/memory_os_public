import os
import sys
import time
import logging
from pathlib import Path
from unittest.mock import patch
from memory_os.core.config import MemoryOSConfig
from memory_os.core.core import MemoryOS
from memory_os.toolkit.transcript_ingestor import TranscriptIngestor
import subprocess

def test_schedule_engine():
    print("\n3. Testing ScheduleEngine (daemon scheduling core)")
    from memory_os.core.daemon import ScheduleEngine

    _log = logging.getLogger("test_schedule_engine")

    # Task fires when interval has elapsed
    counter = [0]
    engine = ScheduleEngine()
    engine.add_task("increment", 5.0, lambda: counter.__setitem__(0, counter[0] + 1))
    engine.tasks[0]["last_run"] = time.time() - 10.0  # simulate 10s ago
    engine.run_pending(_log)
    assert counter[0] == 1, f"Task should have fired once, got {counter[0]}"
    print("-> Task fires when interval elapsed: PASS")

    # Task does NOT fire before its interval
    counter[0] = 0
    engine2 = ScheduleEngine()
    engine2.add_task("early", 60.0, lambda: counter.__setitem__(0, counter[0] + 1))
    engine2.run_pending(_log)  # last_run just set, interval not elapsed
    assert counter[0] == 0, "Task should not fire before interval elapses"
    print("-> Task does not fire before interval: PASS")

    # last_run is updated after task runs
    ran_at = [None]
    engine3 = ScheduleEngine()
    engine3.add_task("ts_check", 0.0, lambda: ran_at.__setitem__(0, time.time()))
    engine3.tasks[0]["last_run"] = 0.0
    before = time.time()
    engine3.run_pending(_log)
    assert engine3.tasks[0]["last_run"] >= before, "last_run should be updated after execution"
    print("-> last_run updated after task executes: PASS")

    # Errors inside a task are caught; scheduler keeps running
    error_fired = [False]

    def bad_task():
        error_fired[0] = True
        raise RuntimeError("deliberate test error")

    engine4 = ScheduleEngine()
    engine4.add_task("bad", 0.0, bad_task)
    engine4.tasks[0]["last_run"] = 0.0
    engine4.run_pending(_log)  # must not raise
    assert error_fired[0], "Error task should still have been called"
    print("-> Task errors are caught gracefully: PASS")


def test_telemetry_recorder():
    print("\n4. Testing TelemetryRecorder (record_run and record_performance)")
    from memory_os.core.telemetry import TelemetryRecorder

    config = MemoryOSConfig()
    db = MemoryOS(config)
    recorder = TelemetryRecorder(db)

    # record_run inserts a row and returns True
    ok = recorder.record_run(
        prompt_name="test_prompt",
        prompt_version="1.0",
        prompt_hash="abc123",
        provider_id="test_provider",
        model_id="test_model_telemetry",
        input_tokens=100,
        output_tokens=50,
        latency_ms=200,
        cost=0.001,
        status="success",
    )
    assert ok is True, "record_run should return True"
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM memory_os_telemetry WHERE prompt_name=? AND model_id=?",
            ("test_prompt", "test_model_telemetry"),
        ).fetchone()
        assert row is not None, "Telemetry row was not inserted"
        assert row["input_tokens"] == 100
        assert row["status"] == "success"
    finally:
        conn.close()
    print("-> record_run inserts correctly: PASS")

    # record_performance inserts a row and returns True
    ok2 = recorder.record_performance(
        algorithm_name="test_algo_auto",
        duration_ms=42,
        metadata='{"detail": "test"}',
    )
    assert ok2 is True, "record_performance should return True"
    conn2 = db.get_connection()
    try:
        row2 = conn2.execute(
            "SELECT * FROM memory_os_performance WHERE algorithm_name=?",
            ("test_algo_auto",),
        ).fetchone()
        assert row2 is not None, "Performance row was not inserted"
        assert row2["duration_ms"] == 42
    finally:
        conn2.close()
    print("-> record_performance inserts correctly: PASS")


def test_daemon_telemetry_loop():
    print("\n5. Testing MemoryDaemon.run_telemetry_analysis() branches")
    from memory_os.core.daemon import MemoryDaemon

    config = MemoryOSConfig()
    transcript = config.root_dir / "agent_context" / "transcript.jsonl"
    daemon = MemoryDaemon(config, transcript)

    patch_target = "memory_os.core.daemon.OSPerformanceAnalyzer"

    # Branch: status=success
    with patch(patch_target) as MockAnalyzer:
        MockAnalyzer.return_value.generate_insights.return_value = {
            "status": "success",
            "created_proposals": 3,
            "proposals": [],
        }
        daemon.run_telemetry_analysis()
        MockAnalyzer.return_value.generate_insights.assert_called_once()
    print("-> success branch completes without error: PASS")

    # Branch: status=skipped
    with patch(patch_target) as MockAnalyzer:
        MockAnalyzer.return_value.generate_insights.return_value = {
            "status": "skipped",
            "reason": "No telemetry data found",
        }
        daemon.run_telemetry_analysis()
        MockAnalyzer.return_value.generate_insights.assert_called_once()
    print("-> skipped branch completes without error: PASS")

    # Branch: status=error
    with patch(patch_target) as MockAnalyzer:
        MockAnalyzer.return_value.generate_insights.return_value = {
            "status": "error",
            "reason": "LLM call failed",
        }
        daemon.run_telemetry_analysis()
        MockAnalyzer.return_value.generate_insights.assert_called_once()
    print("-> error branch completes without error: PASS")

    daemon.remove_pid()


def test_swarm_sync():
    print("\n6. Testing Swarm Sync (File Locking and Conflict Detection)")
    import sys
    from pathlib import Path
    
    scripts_dir = Path(__file__).resolve().parent / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import swarm_sync
    
    # 1. Clear backlog and leases
    ret = swarm_sync.cmd_clear()
    assert ret == 0
    
    # 2. Register first task
    ret = swarm_sync.cmd_register("test_task_1", "claude", "src/memory_os/core/daemon.py")
    assert ret == 0
    
    # 3. Check for conflict (A task on same file should conflict)
    ret = swarm_sync.cmd_register("test_task_2", "codex", "src/memory_os/core/daemon.py")
    assert ret == 1, "Conflict check should prevent registration of overlapping file locks"
    
    # 4. Check for subdirectory conflict
    ret = swarm_sync.cmd_register("test_task_3", "codex", "src/memory_os/core")
    assert ret == 1, "Conflict check should prevent registration of folder lock overlapping files"
    
    # 5. Check non-overlapping registration passes
    ret = swarm_sync.cmd_register("test_task_4", "codex", "src/memory_os/toolkit")
    assert ret == 0
    
    # 6. Update task to completed (which releases locks)
    ret = swarm_sync.cmd_update("test_task_1", "completed", "Test success")
    assert ret == 0
    
    # 7. Registering on freed lock should pass now
    ret = swarm_sync.cmd_register("test_task_2", "codex", "src/memory_os/core/daemon.py")
    assert ret == 0
    
    # 8. Test status visualization (should run without error)
    ret = swarm_sync.cmd_status()
    assert ret == 0
    
    # 9. Clean up
    swarm_sync.cmd_clear()
    print("-> Swarm Sync checks: PASS")


def run_auto_test():
    print("=== Automated Test: Phase 4 (Controlled Automation) ===")
    config = MemoryOSConfig()
    db = MemoryOS(config)

    print("\n1. Testing Human Review Queue")
    # Insert a draft node
    test_node_id = "test_auto_draft_1"
    db.insert_graph_node(test_node_id, "fact", "Automated test draft node", status="draft")
    print(f"-> Inserted draft node: {test_node_id}")

    # Run memory_os review
    print("-> Running 'memory_os review'")
    result = subprocess.run([sys.executable, "-m", "memory_os", "review"], capture_output=True, text=True, cwd=config.root_dir)
    print(result.stdout.strip())
    assert test_node_id in result.stdout, "Draft node not found in review list!"

    # Run memory_os approve
    print(f"-> Running 'memory_os approve {test_node_id}'")
    result2 = subprocess.run([sys.executable, "-m", "memory_os", "approve", test_node_id], capture_output=True, text=True, cwd=config.root_dir)
    print(result2.stdout.strip())
    assert "successfully approved" in result2.stdout, "Approval failed!"

    # Verify review list is empty
    result3 = subprocess.run([sys.executable, "-m", "memory_os", "review"], capture_output=True, text=True, cwd=config.root_dir)
    print("-> 'memory_os review' after approval:")
    print(result3.stdout.strip())

    print("\n2. Testing Budget Manager & Skip Behavior")
    ingestor = TranscriptIngestor(config)
    original_tokens = ingestor.budget._state.get("tokens_used", 0)

    # Force budget exhaustion
    ingestor.budget._state["tokens_used"] = 999999
    ingestor.budget._save_state()
    print("-> Forcing budget to exhausted state (tokens_used=999999).")

    # Try ingestion
    dummy_transcript = config.root_dir / "agent_context" / "transcript.jsonl"
    print("-> Triggering ingestion... (Expected to skip and alert)")
    res = ingestor.ingest(dummy_transcript)
    print(f"-> Ingestion returned: {res} (Expected: [])")
    assert res == [], "Ingestor should return empty list when budget is exhausted!"

    # Restore budget
    ingestor.budget._state["tokens_used"] = original_tokens
    ingestor.budget._save_state()
    print("-> Budget restored.")

    test_schedule_engine()
    test_telemetry_recorder()
    test_daemon_telemetry_loop()
    test_swarm_sync()

    print("\n=== All automated tests passed successfully! ===")

if __name__ == "__main__":
    run_auto_test()
