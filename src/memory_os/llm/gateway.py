from typing import Dict
from .base import LLMProvider
from .types import LLMRequest, LLMResponse

class LLMGateway:
    """Central interface for calling LLMs across different providers."""
    
    def __init__(self):
        self.providers: Dict[str, LLMProvider] = {}

    def register(self, provider: LLMProvider):
        self.providers[provider.name] = provider

    def generate(self, provider_name: str, request: LLMRequest) -> LLMResponse:
        if provider_name not in self.providers:
            raise ValueError(f"Provider not registered: {provider_name}")
        provider = self.providers[provider_name]
        return provider.generate(request)
