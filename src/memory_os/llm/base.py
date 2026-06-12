from abc import ABC, abstractmethod
from .types import LLMRequest, LLMResponse

class LLMProvider(ABC):
    name: str

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        pass

    def healthcheck(self) -> bool:
        return True
