from typing import Callable, Dict, Optional

from memory_os.agent_brain.brain import ActionBrain
from memory_os.agent_brain.responder import Responder
from memory_os.agent_brain.types import ActionRequest, ActionResult
from memory_os.agent_brain.vocabulary import ActionVocabulary, default_memory_os_vocabulary

ActionExecutor = Callable[[ActionRequest], ActionResult]


class Orchestrator:
    """
    The 'law and order' layer: the only thing that ever calls the
    ActionBrain, the only thing that ever executes an action, and the only
    thing that decides whether a Responder gets invoked at all. The
    ActionBrain never talks to the user directly and the Responder never
    decides what to do — each side only sees what this class hands it.

    Validates every ActionRequest against the vocabulary before running it,
    so a brain hallucinating an unregistered action fails closed (an
    ActionResult with ok=False) instead of executing something undefined.
    """

    def __init__(
        self,
        brain: ActionBrain,
        vocabulary: Optional[ActionVocabulary] = None,
        executors: Optional[Dict[str, ActionExecutor]] = None,
        responder: Optional[Responder] = None,
    ):
        self.brain = brain
        self.vocabulary = vocabulary or default_memory_os_vocabulary()
        self.executors: Dict[str, ActionExecutor] = dict(executors or {})
        self.responder = responder

    def register_executor(self, action_name: str, executor: ActionExecutor) -> None:
        if self.vocabulary.get(action_name) is None:
            raise ValueError(
                f"no ActionSpec registered for {action_name!r} — add it to the "
                "vocabulary before wiring an executor for it"
            )
        self.executors[action_name] = executor

    def run(self, task: str) -> ActionResult:
        """Brain -> validate -> execute. Returns the raw ActionResult; use
        handle() instead if you also want a Responder's natural-language
        wrap-up."""
        request = self.brain.propose_action(task, self.vocabulary)

        if self.vocabulary.get(request.action) is None:
            return ActionResult(
                action=request.action,
                ok=False,
                error=f"unknown action: {request.action!r}",
                action_args=dict(request.args),
            )

        executor = self.executors.get(request.action)
        if executor is None:
            return ActionResult(
                action=request.action,
                ok=False,
                error=f"no executor registered for: {request.action!r}",
                action_args=dict(request.args),
            )

        result = executor(request)
        result.action_args = dict(request.args)
        return result

    def handle(self, task: str) -> str:
        """Full loop: brain -> execute -> respond. Raises if no Responder
        is configured — call run() directly when you only want the raw
        ActionResult (e.g. for tests, or a purely programmatic caller)."""
        if self.responder is None:
            raise RuntimeError("no Responder configured on this Orchestrator — use run() instead of handle()")
        result = self.run(task)
        return self.responder.respond(task, result)
