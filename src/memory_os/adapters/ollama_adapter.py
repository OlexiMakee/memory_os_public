import importlib.util
from typing import Any, Dict


def is_available() -> bool:
    """Check if the 'ollama' package is installed and available for import."""
    try:
        return importlib.util.find_spec("ollama") is not None
    except (ImportError, ValueError, AttributeError):
        return False


class OllamaAdapter:
    """Adapter for interacting with a local Ollama server."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url

    def generate(self, prompt: str, model: str = "llama3") -> Dict[str, Any]:
        """Generate content from a local Ollama model.

        Ensures no exceptions escape, handling missing package or network errors cleanly.
        """
        if not is_available():
            return {"ok": False, "detail": "ollama package not installed"}

        try:
            import ollama
        except ImportError as exc:
            return {"ok": False, "detail": f"ollama package not installed: {exc}"}

        try:
            client = ollama.Client(host=self.base_url)
            response = client.generate(model=model, prompt=prompt)

            # Safely handle different potential shapes of the response object
            text = ""
            if isinstance(response, dict):
                text = response.get("response", "")
            elif hasattr(response, "get"):
                text = response.get("response", "")
            else:
                text = getattr(response, "response", "")

            return {
                "ok": True,
                "text": text,
                "model": model,
            }
        except Exception as exc:
            return {
                "ok": False,
                "detail": f"ollama call failed: {exc}",
            }

    def audit(self) -> Dict[str, Any]:
        """Perform a quick, local, non-blocking check on availability and configuration."""
        return {
            "available": is_available(),
            "base_url": self.base_url,
        }
