import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from memory_os.core.config import MemoryOSConfig
from memory_os.ui.data_provider import DefaultGraphDataProvider
from memory_os.ui.server import MemoryOSServer, UIHTTPRequestHandler
from memory_os.toolkit.daemon_client import DaemonResponse


def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "archived_nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "archived_edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _get_json(base_url: str, path: str) -> dict:
    with urlopen(f"{base_url}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(base_url: str, path: str, payload: dict) -> dict:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_ui_space_switch_requires_daemon_confirmation(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    space_dir = config.memory_dir.parent / "dev"
    space_dir.mkdir()
    (space_dir / "nodes.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "memory_os.toolkit.daemon_client.DaemonClient.request",
        lambda self, path, **kwargs: DaemonResponse(
            ok=False,
            status_code=0,
            payload={},
            transport="tcp",
            error="daemon unreachable",
        ),
    )

    server = MemoryOSServer(("127.0.0.1", 0), UIHTTPRequestHandler, DefaultGraphDataProvider(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/switch_space",
            data=json.dumps({"space": "dev"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(request, timeout=5)
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 503
            assert json.loads(exc.read().decode("utf-8"))["error"] == "daemon unreachable"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert server.provider.config.space == "default"


def test_api_tasks_reports_failure_instead_of_masquerading_as_empty(tmp_path, monkeypatch):
    """Regression: /api/tasks used to swallow any TaskKernel exception and return
    200 + an empty list, indistinguishable from "genuinely no tasks". It must now
    surface the failure as a 500 with an error field.
    """
    config = make_config(tmp_path)

    def fail_list_tasks(self, status=None):
        raise RuntimeError("task kernel unavailable")

    monkeypatch.setattr("memory_os.toolkit.task_kernel.TaskKernel.list_tasks", fail_list_tasks)

    server = MemoryOSServer(("127.0.0.1", 0), UIHTTPRequestHandler, DefaultGraphDataProvider(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            _get_json(base_url, "/api/tasks")
            raise AssertionError("expected HTTPError")
        except HTTPError as exc:
            assert exc.code == 500
            body = json.loads(exc.read().decode("utf-8"))
            assert body["tasks"] == []
            assert "task kernel unavailable" in body["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_do_post_unhandled_exception_returns_500_and_logs(tmp_path, monkeypatch, caplog):
    """Regression: do_POST's outer except Exception used to swallow every unhandled
    handler exception with zero logging -- server-side failures were invisible.
    """
    config = make_config(tmp_path)
    _write_jsonl(config.memory_dir / "nodes.jsonl", [{
        "id": "fact:root", "type": "fact", "summary": "s", "status": "draft",
        "trust": "unverified", "evidence": [], "related_nodes": [], "tags": [],
    }])

    def fail_verify(self, node_id):
        raise RuntimeError("boom")

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.MemoryGraphService.verify_node", fail_verify)
    monkeypatch.setattr("memory_os.ui.server.UIHTTPRequestHandler._memory_write_read_only", lambda self: False)

    server = MemoryOSServer(("127.0.0.1", 0), UIHTTPRequestHandler, DefaultGraphDataProvider(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        with caplog.at_level("ERROR", logger="memory_os.ui.server"):
            try:
                _post_json(base_url, "/api/nodes/verify", {"id": "fact:root"})
                raise AssertionError("expected HTTPError")
            except HTTPError as exc:
                assert exc.code == 500
        assert any("boom" in record.message for record in caplog.records)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ui_memory_api_exposes_runtime_signals(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:root",
                "type": "fact",
                "summary": "task ids and status reports drive routing",
                "status": "verified",
                "trust": "verified",
                "confidence": 0.4,
                "tags": ["routing"],
                "evidence": ["a.py"],
                "related_nodes": ["fact:leaf"],
            },
            {
                "id": "fact:root-copy",
                "type": "fact",
                "summary": "status reports and task ids drive routing",
                "status": "verified",
                "trust": "verified",
                "tags": ["routing"],
                "evidence": ["a.py"],
                "related_nodes": [],
            },
            {
                "id": "fact:leaf",
                "type": "fact",
                "summary": "leaf node",
                "status": "verified",
                "trust": "verified",
                "tags": ["routing"],
                "evidence": ["b.py"],
                "related_nodes": [],
            },
        ],
    )
    _write_jsonl(
        config.memory_dir / "edges.jsonl",
        [{"source": "fact:root", "target": "fact:leaf", "type": "contains"}],
    )

    class FakeEvalRunner:
        def __init__(self, config):
            self.config = config

        def list_suites(self):
            return [{"name": "retrieval-relevance"}]

        def run(self, suite):
            return {"ok": True, "recall_at_5": 1.0, "pass_threshold": 1.0}

    monkeypatch.setattr("memory_os.toolkit.memory_graph_service.EvalRunner", FakeEvalRunner, raising=False)

    server = MemoryOSServer(("127.0.0.1", 0), UIHTTPRequestHandler, DefaultGraphDataProvider(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        health = _get_json(base_url, "/api/memory/health")
        curate = _get_json(base_url, "/api/memory/curate?limit=5")
        browse = _get_json(base_url, "/api/memory/browse?node_id=fact:root")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert health["low_confidence_count"] == 1
    assert health["low_confidence_nodes"] == ["fact:root"]
    assert curate["primary_recommendation"] == "merge-preview"
    assert curate["next_actions"][0]["action"] == "merge-preview"
    assert browse["results"][0]["focus_signal"]["degree"] == 1
    assert "outbound=1" in browse["results"][0]["focus_signal"]["reason"]


def test_ui_memory_management_rest_endpoints(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    server = MemoryOSServer(("127.0.0.1", 0), UIHTTPRequestHandler, DefaultGraphDataProvider(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        created = _post_json(base_url, "/api/nodes/upsert", {
            "id": "fact:ui",
            "summary": "ui memory api source",
            "status": "verified",
            "tags": ["ui"],
        })
        _post_json(base_url, "/api/nodes/upsert", {
            "id": "fact:keep",
            "summary": "ui memory api target",
            "status": "verified",
        })
        assert created["status"] == "ok"

        updated = _post_json(base_url, "/api/nodes/update", {
            "id": "fact:ui",
            "summary": "ui memory api source updated",
            "tags": ["ui", "rest"],
        })
        assert updated["updated"] is True
        assert "rest" in updated["node"]["tags"]

        pinned = _post_json(base_url, "/api/nodes/pin", {"id": "fact:ui", "pinned": True})
        assert pinned["pinned"] is True
        assert "pinned" in pinned["node"]["tags"]

        verified = _post_json(base_url, "/api/nodes/verify", {"id": "fact:ui"})
        assert verified["verified"] is True
        assert _get_json(base_url, "/api/memory/node?id=fact:ui")["node"]["protocol_level"] == 99

        edge = _post_json(base_url, "/api/edges/create", {
            "source": "fact:ui",
            "target": "fact:keep",
            "type": "depends_on",
        })
        assert edge["status"] == "ok"
        assert _get_json(base_url, "/api/memory/edges?source=fact:ui")["total"] == 1

        timeline = _get_json(base_url, "/api/memory/timeline?days=1&type=fact")
        timeline_ids = [node["id"] for day in timeline["days"] for node in day["nodes"]]
        assert "fact:ui" in timeline_ids

        deleted_edge = _post_json(base_url, "/api/edges/delete", {
            "source": "fact:ui",
            "target": "fact:keep",
            "type": "depends_on",
        })
        assert deleted_edge["deleted"] is True

        _post_json(base_url, "/api/edges/create", {
            "source": "fact:ui",
            "target": "fact:keep",
            "type": "depends_on",
        })
        merged = _post_json(base_url, "/api/nodes/merge", {"source": "fact:ui", "target": "fact:keep"})
        assert merged["merged"] is True
        assert "Merged from" in _get_json(base_url, "/api/memory/node?id=fact:keep")["node"]["summary"]

        export_request = Request(f"{base_url}/api/memory/export")
        with urlopen(export_request, timeout=5) as response:
            exported = json.loads(response.read().decode("utf-8"))
            disposition = response.headers.get("Content-Disposition", "")
        assert 'filename="memory_export.json"' in disposition
        assert any(node["id"] == "fact:keep" for node in exported["nodes"])

        events = _get_json(base_url, "/api/memory/events?node_id=fact:keep")
        assert any(event.get("event") == "memory.ui.node.merged" for event in events["events"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ui_memory_delete_archive_and_edge_upsert_endpoints(tmp_path, monkeypatch):
    """Covers the 3 write endpoints not exercised by
    test_ui_memory_management_rest_endpoints, after the POST-handler dedup
    (_handle_memory_write_action) -- confirms not_found-status handling and
    the edges/upsert use_not_found_status=False path still behave correctly.
    """
    config = make_config(tmp_path)
    monkeypatch.chdir(tmp_path)

    server = MemoryOSServer(("127.0.0.1", 0), UIHTTPRequestHandler, DefaultGraphDataProvider(config))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        _post_json(base_url, "/api/nodes/upsert", {
            "id": "fact:archive-me",
            "summary": "will be archived",
            "status": "verified",
        })
        _post_json(base_url, "/api/nodes/upsert", {
            "id": "fact:delete-me",
            "summary": "will be deleted",
            "status": "verified",
        })
        _post_json(base_url, "/api/nodes/upsert", {"id": "fact:edge-a", "summary": "a", "status": "verified"})
        _post_json(base_url, "/api/nodes/upsert", {"id": "fact:edge-b", "summary": "b", "status": "verified"})

        archived = _post_json(base_url, "/api/nodes/archive", {"id": "fact:archive-me", "reason": "test"})
        assert archived["archived"] is True
        assert _get_json(base_url, "/api/memory/node?id=fact:archive-me")["node"]["status"] == "archived"

        try:
            _post_json(base_url, "/api/nodes/archive", {"id": "fact:does-not-exist"})
            raise AssertionError("expected HTTPError for archiving a missing node")
        except HTTPError as exc:
            assert exc.code == 404
            assert json.loads(exc.read().decode("utf-8"))["status"] == "not_found"

        deleted = _post_json(base_url, "/api/nodes/delete", {"id": "fact:delete-me"})
        assert deleted["deleted"] is True
        try:
            _get_json(base_url, "/api/memory/node?id=fact:delete-me")
            raise AssertionError("expected HTTPError for a deleted node")
        except HTTPError as exc:
            assert exc.code == 404

        upserted_edge = _post_json(base_url, "/api/edges/upsert", {
            "source": "fact:edge-a",
            "target": "fact:edge-b",
            "type": "depends_on",
        })
        assert upserted_edge["status"] == "ok"
        assert _get_json(base_url, "/api/memory/edges?source=fact:edge-a")["total"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
