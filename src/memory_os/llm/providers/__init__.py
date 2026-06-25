# No eager imports here: importing one provider module must not import every
# other provider, since mlx_provider.py's mlx_lm dependency can perform a
# native abort on import on some systems (an uncaught native exception, not
# a catchable Python ImportError). Import the specific provider you need
# directly, e.g.:
#   from memory_os.llm.providers.openai_compatible_provider import OpenAICompatibleProvider

__all__ = ["OllamaProvider", "OpenAICompatibleProvider", "MLXProvider"]


def __getattr__(name):
    """Lazy attribute access so `from memory_os.llm.providers import X` still
    works for callers that want that convenience, without eagerly importing
    every provider module just because the package was imported."""
    if name == "OllamaProvider":
        from .ollama_provider import OllamaProvider
        return OllamaProvider
    if name == "OpenAICompatibleProvider":
        from .openai_compatible_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider
    if name == "MLXProvider":
        from .mlx_provider import MLXProvider
        return MLXProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
