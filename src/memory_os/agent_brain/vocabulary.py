from typing import Dict, Iterable, List, Optional

from memory_os.agent_brain.types import ActionSpec


class ActionVocabulary:
    """
    Registry of ActionSpecs available to one ActionBrain call. This is both
    the `<available_actions>` block the brain sees at inference time and
    the lookup table Orchestrator uses to validate/dispatch a request — one
    source of truth for what an agent can do, instead of two that can drift.
    """

    def __init__(self, specs: Optional[Iterable[ActionSpec]] = None):
        self._specs: Dict[str, ActionSpec] = {s.name: s for s in (specs or [])}

    def register(self, spec: ActionSpec) -> None:
        self._specs[spec.name] = spec

    def get(self, name: str) -> Optional[ActionSpec]:
        return self._specs.get(name)

    def names(self) -> List[str]:
        return sorted(self._specs)

    def to_prompt_block(self) -> str:
        """
        Render the minimal `<available_actions>` text the design calls for:
        name + one-line description, nothing else. No 30 rules, no examples
        unless the adapter specifically needs few-shot priming — the LoRA
        is what should carry the calling convention, not the prompt.
        """
        lines = ["<available_actions>"]
        for name in self.names():
            lines.append(f"{name}: {self._specs[name].description}")
        lines.append("</available_actions>")
        return "\n".join(lines)


def default_memory_os_vocabulary() -> ActionVocabulary:
    """
    The action vocabulary backed by memory_os's own existing functionality
    — MemorySearcher and LifecycleManager already do the work; this just
    exposes them as actions an ActionBrain can name. Extend with more
    ActionSpecs (sql.query, web.search, ...) as real executors exist for
    them; an unregistered action is a vocabulary gap, not a brain failure.
    """
    return ActionVocabulary([
        ActionSpec(
            name="memory.search",
            description="Search the memory graph (FTS5 + graph traversal).",
            args_schema={"query": "string", "depth": "integer"},
        ),
        ActionSpec(
            name="memory.write",
            description="Propose a new memory node (lands as draft, not verified).",
            args_schema={"id": "string", "type": "string", "summary": "string"},
            risk="write",
        ),
        ActionSpec(
            name="file.read",
            description="Read one local file by path, confined to the project root.",
            args_schema={"path": "string"},
        ),
    ])
