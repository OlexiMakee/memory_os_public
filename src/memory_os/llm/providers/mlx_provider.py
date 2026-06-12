import time
from ..base import LLMProvider
from ..types import LLMRequest, LLMResponse

try:
    from mlx_lm import load, generate
except ImportError:
    load = None
    generate = None

class MLXProvider(LLMProvider):
    name = "mlx"

    def __init__(self, model_path: str):
        if load is None:
            raise ImportError("mlx_lm package is required for MLXProvider")
        self.model_path = model_path
        self.model, self.tokenizer = load(model_path)
        self._generate = generate

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.time()
        prompt = self._messages_to_prompt(request)
        
        content = self._generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=request.options.max_tokens,
            temp=request.options.temperature,
            verbose=False,
        )
        
        latency = time.time() - start
        
        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.name,
            latency_sec=latency,
        )

    def _messages_to_prompt(self, request: LLMRequest) -> str:
        parts = []
        for msg in request.messages:
            parts.append(f"{msg.role.upper()}:\n{msg.content}")
        parts.append("ASSISTANT:\n")
        return "\n\n".join(parts)
