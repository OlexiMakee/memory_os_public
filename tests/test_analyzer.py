import json

from memory_os.core.config import MemoryOSConfig
from memory_os.toolkit.analyzer import OSPerformanceAnalyzer


class _FakeMemoryOS:
    def __init__(self, *a, **kw):
        pass


def test_generate_insights_does_not_force_cloud_provider(tmp_path, monkeypatch):
    """Regression: generate_insights() used to hardcode provider="gemini",
    which skips the local-first llama_server/llama_cpp/ollama chain entirely
    and fails outright whenever no GEMINI_API_KEY is set (the normal state
    for this local-first project) -- logging an ERROR every 6h forever."""
    monkeypatch.setattr("memory_os.toolkit.analyzer.MemoryOS", _FakeMemoryOS)

    config = MemoryOSConfig()
    analyzer = OSPerformanceAnalyzer(config)
    monkeypatch.setattr(analyzer, "_gather_digest", lambda: "some real telemetry content")

    captured = {}

    def fake_call_llm(*args, **kwargs):
        captured.update(kwargs)
        return json.dumps({"proposals": []})

    monkeypatch.setattr(analyzer.llm, "call_llm", fake_call_llm)
    monkeypatch.setattr(analyzer, "proposals_path", tmp_path / "admin_proposals.jsonl")

    result = analyzer.generate_insights()

    assert result["status"] == "success"
    assert captured.get("provider") is None
    assert captured.get("model") is None
