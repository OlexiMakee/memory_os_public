import pytest
from memory_os.cli import cmd_transition

def test_debug(monkeypatch):
    class DummyLifecycle:
        def __init__(self, config):
            pass
        def transition(self, validator=None, min_confidence=0.5):
            return 0
    monkeypatch.setattr("memory_os.cli_groups.memory_cmds.LifecycleManager", DummyLifecycle)
    import memory_os.cli_groups.memory_cmds as mem
    print("PATCHED:", mem.LifecycleManager == DummyLifecycle)
    print("GLOBALS:", cmd_transition.__globals__["LifecycleManager"] == DummyLifecycle)
    print("IS DUMMY?", mem.LifecycleManager is DummyLifecycle)

