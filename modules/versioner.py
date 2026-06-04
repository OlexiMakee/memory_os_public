import hashlib
from typing import Dict, Optional

class PromptVersioner:
    """Manages prompt template registries, versions, and SHA-256 integrity mapping."""

    def __init__(self):
        self._registry: Dict[str, Dict[str, str]] = {}

    def register_prompt(self, name: str, version: str, template_text: str):
        """Register a prompt template under a specific version string."""
        self._registry[name] = {
            "version": version,
            "template": template_text,
            "hash": self.compute_hash(template_text)
        }

    def get_prompt(self, name: str) -> Optional[Dict[str, str]]:
        """Get registered prompt details (version, template, hash)."""
        return self._registry.get(name)

    @staticmethod
    def compute_hash(template_text: str) -> str:
        """Compute 16-character SHA-256 hash of prompt template string."""
        if not template_text:
            return ""
        return hashlib.sha256(template_text.strip().encode("utf-8")).hexdigest()[:16]
