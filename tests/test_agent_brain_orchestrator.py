from memory_os.agent_brain.brain import ScriptedActionBrain
from memory_os.agent_brain.orchestrator import Orchestrator
from memory_os.agent_brain.types import ActionRequest, ActionResult
from memory_os.agent_brain.vocabulary import default_memory_os_vocabulary


def test_orchestrator_attaches_action_args_to_executor_result():
    request = ActionRequest(action="memory.search", args={"query": "daemon IPC"})
    brain = ScriptedActionBrain({"daemon": request})
    orchestrator = Orchestrator(
        brain=brain,
        vocabulary=default_memory_os_vocabulary(),
        executors={"memory.search": lambda _request: ActionResult(action="memory.search", ok=True, data=[])},
    )

    result = orchestrator.run("daemon")

    assert result.action_args == {"query": "daemon IPC"}
    assert result.to_dict()["action_args"] == {"query": "daemon IPC"}


def test_orchestrator_attaches_action_args_to_validation_failure():
    request = ActionRequest(action="unknown.action", args={"value": 42})
    brain = ScriptedActionBrain({"bad": request})
    orchestrator = Orchestrator(brain=brain, vocabulary=default_memory_os_vocabulary())

    result = orchestrator.run("bad")

    assert result.ok is False
    assert result.action_args == {"value": 42}
