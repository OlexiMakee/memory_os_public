from abc import ABC, abstractmethod
from typing import Optional

from memory_os.agent_brain.types import ActionResult


class Responder(ABC):
    """
    Turns a finished ActionResult into natural language for the user — the
    human-language/style/personality layer the philosophy explicitly keeps
    OUT of the action brain (see docs/encyclopedia/agent_brain.md). Backed
    by an instruct or creative-tuned model, optionally with its own
    LoRA (e.g. creative_dirty_humor.lora, news_editor.lora) selected per
    task — never by the same model/adapter that produced the action.
    """

    @abstractmethod
    def respond(self, task: str, result: ActionResult) -> str:
        ...


class LocalLLMResponder(Responder):
    """
    Same local-first LLM chain as LocalLLMActionBrain, but with a normal
    system prompt — this is deliberately where personality/tone/style
    shows up, decoupled from action generation so a bad day for the
    responder's prose never corrupts the action brain's tool calls.
    """

    def __init__(
        self,
        system_prompt: str = "You are a helpful assistant.",
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.system_prompt = system_prompt
        self.provider = provider
        self.model = model

    def respond(self, task: str, result: ActionResult) -> str:
        from memory_os.core.llm_service import DefaultLlmProviderService

        outcome = result.data if result.ok else f"Error: {result.error}"
        # Pure conversational (no action taken): send task directly.
        # Action result: include structured context for formatting.
        if result.action == "chat" and not outcome:
            user_message = task
        else:
            user_message = f"Task: {task}\nAction: {result.action}\nResult: {outcome}"
        return DefaultLlmProviderService().call_llm(
            user_message=user_message,
            system_prompt=self.system_prompt,
            provider=self.provider,
            model=self.model,
            lora_role="responder",
        )
