import json
from typing import TypeVar, Type, Optional, Any
from pydantic import BaseModel, ValidationError

T = TypeVar('T', bound=BaseModel)

class LLMResponseValidator:
    """Validates and parses JSON strings from LLM responses into Pydantic models."""

    @staticmethod
    def parse(raw: str, model_class: Type[T]) -> Optional[T]:
        """Attempt to parse a raw JSON string into a specific Pydantic model."""
        # Sometimes LLMs wrap JSON in markdown blocks
        clean_raw = LLMResponseValidator._strip_markdown(raw)
        
        try:
            data = json.loads(clean_raw)
            return model_class(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            # Here we could implement fallback logic, e.g., asking the LLM to repair the JSON
            # For now, we return None to signify validation failure
            return None

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Strip ```json and ``` tags from LLM output."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()
