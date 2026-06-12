from dataclasses import dataclass, field
from typing import Literal, Optional, Dict, Any, List

Role = Literal["system", "user", "assistant", "tool"]

@dataclass
class ChatMessage:
    role: Role
    content: str

@dataclass
class LLMOptions:
    temperature: float = 0.2
    top_p: float = 0.9
    max_tokens: int = 512
    context_window: int = 4096
    stream: bool = False
    stop: Optional[List[str]] = None
    json_mode: bool = False

@dataclass
class LLMRequest:
    messages: List[ChatMessage]
    model: str
    task_type: str = "general"
    options: LLMOptions = field(default_factory=LLMOptions)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    latency_sec: float
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tokens_per_sec: Optional[float] = None
    raw: Optional[Dict[str, Any]] = None
