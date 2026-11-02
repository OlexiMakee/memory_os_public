from memory_os.core.llm_service import (
    _OLLAMA_MODEL_CACHE,
    _call_llm_direct,
    _discover_llama_cpp,
    _discover_ollama_model,
    ollama_http_health,
)


def test_discover_llama_cpp_has_no_hardcoded_personal_path(monkeypatch, tmp_path):
    """Regression: LLAMA_CPP_BIN's default used to be a personal dev-machine
    absolute path; any other machine/user got a silent no-op fallback that
    contradicted _discover_llama_cpp's own "don't assume a hardcoded
    location" intent. Default must come from PATH via shutil.which instead.
    """
    model = tmp_path / "model.gguf"
    model.write_text("stub", encoding="utf-8")
    monkeypatch.setenv("LLAMA_CPP_MODEL", str(model))
    monkeypatch.delenv("LLAMA_CPP_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert _discover_llama_cpp() is None


def test_discover_ollama_model_uses_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("OLLAMA_MODEL override should not hit the network")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    assert _discover_ollama_model("http://127.0.0.1:11434") == "qwen3:4b"


def test_ollama_http_health_uses_tags_api(monkeypatch):
    _OLLAMA_MODEL_CACHE.clear()
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"models":[{"name":"gemma3:4b"}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())

    health = ollama_http_health("http://127.0.0.1:11434")

    assert health["ok"] is True
    assert health["model"] == "gemma3:4b"
    assert health["host"] == "http://127.0.0.1:11434"


def test_llama_cpp_precedes_ollama_and_cloud_fallbacks(monkeypatch):
    calls = []

    monkeypatch.delenv("LLAMA_SERVER_URL", raising=False)
    monkeypatch.setenv("LLAMA_CPP_MODEL", "/tmp/model.gguf")
    monkeypatch.setenv("LLAMA_CPP_BIN", "/tmp/llama-completion")
    monkeypatch.setenv("OLLAMA_MODEL", "should-not-be-used")
    monkeypatch.setenv("GEMINI_API_KEY", "should-not-be-used")

    def fake_discover_server(*_args, **_kwargs):
        calls.append("llama_server")
        return None

    def fake_discover_cpp(*_args, **_kwargs):
        calls.append("llama_cpp")
        return ("/tmp/llama-completion", "/tmp/model.gguf", None)

    def fake_call_cpp(*_args, **_kwargs):
        calls.append("call_llama_cpp")
        return "local result"

    def fail_ollama(*_args, **_kwargs):
        raise AssertionError("Ollama must not be reached when llama_cpp is available")

    monkeypatch.setattr("memory_os.core.llm_service._discover_llama_server", fake_discover_server)
    monkeypatch.setattr("memory_os.core.llm_service._discover_llama_cpp", fake_discover_cpp)
    monkeypatch.setattr("memory_os.core.llm_service._call_llama_cpp", fake_call_cpp)
    monkeypatch.setattr("memory_os.core.llm_service._discover_ollama_model", fail_ollama)

    assert _call_llm_direct("user", "system") == "local result"
    assert calls == ["llama_server", "llama_cpp", "call_llama_cpp"]


def test_llama_server_precedes_llama_cpp_when_reachable(monkeypatch):
    calls = []

    def fake_discover_server(*_args, **_kwargs):
        calls.append("llama_server")
        return "http://127.0.0.1:8080"

    def fake_call_server(*_args, **_kwargs):
        calls.append("call_llama_server")
        return "server result"

    def fail_discover_cpp(*_args, **_kwargs):
        raise AssertionError("llama_cpp must not be probed after a healthy llama_server")

    monkeypatch.setattr("memory_os.core.llm_service._discover_llama_server", fake_discover_server)
    monkeypatch.setattr("memory_os.core.llm_service._call_llama_server", fake_call_server)
    monkeypatch.setattr("memory_os.core.llm_service._discover_llama_cpp", fail_discover_cpp)

    assert _call_llm_direct("user", "system") == "server result"
    assert calls == ["llama_server", "call_llama_server"]


def test_pinned_ollama_provider_skips_earlier_local_providers(monkeypatch):
    calls = []

    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:4b")

    def fail_discover_server(*_args, **_kwargs):
        raise AssertionError("Pinned ollama must not probe llama_server")

    def fail_discover_cpp(*_args, **_kwargs):
        raise AssertionError("Pinned ollama must not probe llama_cpp")

    def fake_call_ollama(*_args, **_kwargs):
        calls.append("call_ollama")
        return "ollama result"

    monkeypatch.setattr("memory_os.core.llm_service._discover_llama_server", fail_discover_server)
    monkeypatch.setattr("memory_os.core.llm_service._discover_llama_cpp", fail_discover_cpp)
    monkeypatch.setattr("memory_os.core.llm_service._call_ollama", fake_call_ollama)

    assert _call_llm_direct("user", "system", provider="ollama") == "ollama result"
    assert calls == ["call_ollama"]
