import time
from ..base import LLMProvider
from ..types import LLMRequest, LLMResponse

class MLXProvider(LLMProvider):
    name = "mlx"

    def __init__(self, model_path: str):
        # Imported lazily, not at module level: mlx_lm performs native Metal
        # initialization on import that can abort the whole process with an
        # uncaught native exception (not a catchable Python ImportError) on
        # some systems. Importing this MODULE must stay safe even when
        # mlx_lm itself is broken; only constructing a provider should risk it.
        try:
            from mlx_lm import load, generate
        except ImportError:
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
