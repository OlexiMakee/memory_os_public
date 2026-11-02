"""
Constrained-decoding interface.

Defines a backend-agnostic way to describe the shape an ActionBrain's
output must take. Implementations are backend-specific (a llama.cpp GBNF
grammar, Ollama's `format` JSON-schema parameter, the `outlines`/`guidance`
Python libraries) and actually run on whichever machine serves the model —
nothing in this module performs decoding itself. It exists so the schema
is described once, centrally, instead of redefined per backend.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from memory_os.agent_brain.vocabulary import ActionVocabulary


class GrammarConstraint(ABC):
    """One method: turn a vocabulary into whatever schema/grammar format
    a specific inference backend expects."""

    @abstractmethod
    def render(self, vocabulary: ActionVocabulary) -> Any:
        ...


class JSONSchemaConstraint(GrammarConstraint):
    """
    Renders a plain JSON Schema for {"action": <one of vocabulary.names()>,
    "args": {...}} — what Ollama's `format` parameter and most
    OpenAI-compatible `response_format` implementations accept directly.
    This is the schema LocalLLMActionBrain documents but does not yet pass
    to a backend — wiring it through is real work for whichever serving
    stack (Ollama `format=`, llama.cpp grammar, outlines) ends up hosting
    the trained adapter on the GPU machine.
    """

    def render(self, vocabulary: ActionVocabulary) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": vocabulary.names()},
                "args": {"type": "object"},
            },
            "required": ["action", "args"],
            "additionalProperties": False,
        }
