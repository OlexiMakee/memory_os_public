import time
from typing import Optional

from ..base import LLMProvider
from ..types import LLMRequest, LLMResponse

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str = "local"):
        if OpenAI is None:
            raise ImportError("openai package is required for OpenAICompatibleProvider")
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        start = time.time()
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
        ]
        
        kwargs = {
            "model": request.model,
            "messages": messages,
            "temperature": request.options.temperature,
            "top_p": request.options.top_p,
            "max_tokens": request.options.max_tokens,
            "stream": False,
        }
        
        if request.options.stop:
            kwargs["stop"] = request.options.stop
            
        if request.options.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            
        response = self.client.chat.completions.create(**kwargs)
        
        latency = time.time() - start
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        
        return LLMResponse(
            content=content,
            model=request.model,
            provider=self.name,
            latency_sec=latency,
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )
