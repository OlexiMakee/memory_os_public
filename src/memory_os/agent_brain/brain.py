from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from memory_os.agent_brain.types import ActionRequest
from memory_os.agent_brain.vocabulary import ActionVocabulary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule-based fast path — handles obvious intent without LLM call.
# Covers Ukrainian patterns missed by the base model prior (e.g. "запам'ятай").
# ---------------------------------------------------------------------------

# Tokens that signal "store this new information" (memory.write)
_WRITE_TRIGGERS: List[str] = [
    # Ukrainian
    "запам'ятай", "запамятай", "запам`ятай",
    "збережи", "запиши", "зафіксуй", "додай до пам",
    "вивчи це", "запомни",
    # English explicit store (not "remember" alone — too ambiguous)
    "store this", "save this", "add this to memory", "note this",
    "remember this rule", "remember this fact",
]

# Tokens that signal "look up existing information" (memory.search)
_SEARCH_TRIGGERS: List[str] = [
    # Ukrainian
    "знайди", "пошукай", "що ти знаєш", "що таке",
    "хто такий", "розкажи про", "нагадай мені", "покажи мені",
    # English
    "what do you know about", "search for", "look up", "find in memory",
]


def _fast_path_action(task: str) -> Optional[ActionRequest]:
    """Return an ActionRequest for clear-signal tasks without calling the LLM.

    Extracts content that follows the trigger keyword as the action argument.
    Returns None when no trigger matches, letting the LLM handle ambiguous cases.
    """
    t = task.lower()
    for kw in _WRITE_TRIGGERS:
        if kw in t:
            idx = t.index(kw) + len(kw)
            content = task[idx:].strip(" :,\n")
            if content:
                return ActionRequest(
                    action="memory.write",
                    args={"summary": content, "type": "fact"},
                )
    for kw in _SEARCH_TRIGGERS:
        if kw in t:
            idx = t.index(kw) + len(kw)
            query = task[idx:].strip(" :,\n") or task
            return ActionRequest(
                action="memory.search",
                args={"query": query},
            )
    return None


class ActionBrain(ABC):
    """
    Produces exactly one ActionRequest for a task — nothing else. In the
    target design this is backed by a base model + an action-only LoRA
    (see docs/encyclopedia/agent_brain.md): no chat persona, no refusals,
    no explaining itself, just pattern -> action. What backs it is an
    implementation detail behind this one method; Orchestrator never knows
    or cares which subclass it's holding.
    """

    @abstractmethod
    def propose_action(self, task: str, vocabulary: ActionVocabulary) -> ActionRequest:
        ...


class ScriptedActionBrain(ActionBrain):
    """
    Fixed-mapping stand-in for a real model. Lets Orchestrator and
    ActionExecutors be built and tested end-to-end on a machine with no
    GPU and no trained adapter — which is the whole point: prove the
    surrounding system before the model exists, not after.
    """

    def __init__(self, mapping: Dict[str, ActionRequest]):
        self.mapping = mapping  # task substring -> fixed ActionRequest

    def propose_action(self, task: str, vocabulary: ActionVocabulary) -> ActionRequest:
        for key, action in self.mapping.items():
            if key in task:
                return action
        raise LookupError(f"ScriptedActionBrain has no mapping for task: {task!r}")


class LocalLLMActionBrain(ActionBrain):
    """
    Calls out through the existing local-first LLM chain
    (core.llm_service.DefaultLlmProviderService — Ollama first, then free
    cloud, see feedback memory on local-first) with the minimal
    <task>/<available_actions>/<answer_format> prompt the design calls
    for, and parses the single JSON object it returns.

    This is the real bridge to the trained adapter: once the action-only
    LoRA exists (trained on the GPU machine, served via Ollama per
    docs/encyclopedia/lora_training.md), point `model` at that Ollama tag
    and this class needs no changes. Until then it will just fail through
    the same local-first chain like any other unconfigured provider.

    Passes a JSONSchemaConstraint (grammar.py) through as `response_schema`
    — honored as a real decode-time constraint when the active backend is
    Ollama, silently best-effort (prompt instructions only) on the cloud
    fallbacks. Either way the result is still parsed/validated here: a
    schema narrows what a well-behaved backend *can* emit, it doesn't
    replace checking what actually came back.
    """

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider
        self.model = model

    def propose_action(self, task: str, vocabulary: ActionVocabulary) -> ActionRequest:
        import json

        from memory_os.agent_brain.grammar import JSONSchemaConstraint
        from memory_os.core.llm_service import DefaultLlmProviderService

        # Fast path: rule-based matching for obvious Ukrainian/English patterns.
        # Avoids LLM round-trip for the ~60% of requests that are unambiguous.
        fast = _fast_path_action(task)
        if fast and fast.action in vocabulary.names():
            logger.debug(f"[ActionBrain] fast-path hit: {fast.action}")
            return fast

        routing_hints = (
            "<routing_hints>\n"
            "- Use memory.write when the task asks to remember, store, save, record, add, or learn a new rule/fact.\n"
            "- Use memory.search when the task asks to find, search, recall, or inspect existing memory.\n"
            "- Use file.read when the task asks to read, show, open, or display a project file.\n"
            "</routing_hints>\n"
        )
        argument_hints = (
            "<argument_hints>\n"
            "- memory.search args: {\"query\": string}.\n"
            "- memory.write args: {\"summary\": string, \"type\": \"rule\"|\"fact\"}. Do not leave summary empty.\n"
            "- file.read args: {\"path\": string}.\n"
            "</argument_hints>\n"
        )
        prompt = (
            f"<task>\n{task}\n</task>\n"
            f"{vocabulary.to_prompt_block()}\n"
            f"{routing_hints}"
            f"{argument_hints}"
            "<answer_format>\n"
            'Respond with exactly one JSON object: {"action": "<name>", "args": {...}}. '
            "No other text.\n"
            "</answer_format>"
        )
        schema = JSONSchemaConstraint().render(vocabulary)
        raw = DefaultLlmProviderService().call_llm(
            user_message=prompt,
            system_prompt="",
            provider=self.provider,
            model=self.model,
            response_schema=schema,
        )
        parsed = json.loads(raw)
        if parsed.get("action") not in vocabulary.names():
            raise ValueError(f"model returned an action outside the vocabulary: {parsed.get('action')!r}")
        return ActionRequest(action=parsed["action"], args=parsed.get("args", {}))
