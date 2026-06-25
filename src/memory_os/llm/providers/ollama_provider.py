import time
from typing import Optional

from memory_os.core.safe_id import validate_outbound_base_url

from ..base import LLMProvider
from ..types import LLMRequest, LLMResponse

try:
    import ollama
except ImportError:
    ollama = None

class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, host: str = "http://localhost:11434", keep_alive: str = "30m", timeout: float = 60.0):
        if ollama is None:
            raise ImportError("ollama package is required for OllamaProvider")
        validate_outbound_base_url(host, "host")
        self.client = ollama.Client(host=host, timeout=timeout)
        self.keep_alive = keep_alive

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.time()
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
        ]
        
        options = {
            "temperature": request.options.temperature,
            "top_p": request.options.top_p,
            "num_predict": request.options.max_tokens,
            "num_ctx": request.options.context_window,
        }
        
        if request.options.stop:
            options["stop"] = request.options.stop
            
        # Optional: json mode
        format_param = "json" if request.options.json_mode else ""
            
        response = self.client.chat(
            model=request.model,
            messages=messages,
            stream=False,
            keep_alive=self.keep_alive,
            options=options,
            format=format_param
        )
        
        latency = time.time() - start
        content = response["message"]["content"]
        eval_count = response.get("eval_count")
        eval_duration = response.get("eval_duration")
        
        tokens_per_sec = None
        if eval_count and eval_duration:
            tokens_per_sec = eval_count / (eval_duration / 1_000_000_000)
            
        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.name,
            latency_sec=latency,
            output_tokens=eval_count,
            tokens_per_sec=tokens_per_sec,
            raw=response,
        )
