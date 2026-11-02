import json
from pathlib import Path
from unittest.mock import MagicMock

from memory_os.core.config import MemoryOSConfig
from memory_os.modules.compactor import MemoryCompactor

def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "agent_context").mkdir(exist_ok=True)
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")

def test_compactor_compress_graph_ignores_pinned_nodes(tmp_path):
    config = make_config(tmp_path)
    
    _write_jsonl(
        config.memory_dir / "nodes.jsonl",
        [
            {
                "id": "fact:regular",
                "type": "fact",
                "summary": "This is a regular verified node",
                "status": "verified",
                "tags": []
            },
            {
                "id": "fact:pinned",
                "type": "fact",
                "summary": "This is a pinned verified node",
                "status": "verified",
                "tags": ["pinned"]
            },
            {
                "id": "fact:another",
                "type": "fact",
                "summary": "This is another regular node",
                "status": "verified",
                "tags": ["some-tag"]
            }
        ]
    )

    mock_llm = MagicMock()
    # Provide a mock response so json.loads(strip_json_code_fence(...)) works and doesn't crash, 
    # but we just want to verify what it was called with.
    mock_llm.call_llm.return_value = '{"nodes": [], "edges": []}'

    compactor = MemoryCompactor(config=config, llm_service=mock_llm)
    
    # We call compress_graph
    compactor.compress_graph()

    # Verify that mock_llm.call_llm was called and check the user_message argument
    assert mock_llm.call_llm.called
    
    # The first argument (or the user_message arg) to call_llm
    call_args = mock_llm.call_llm.call_args
    user_message = call_args[0][0]
    
    user_msg_data = json.loads(user_message)
    verified_nodes = user_msg_data.get("verified_nodes", [])
    
    # We expect fact:regular and fact:another, but NOT fact:pinned
    node_ids = [n["id"] for n in verified_nodes]
    assert "fact:regular" in node_ids
    assert "fact:another" in node_ids
    assert "fact:pinned" not in node_ids
