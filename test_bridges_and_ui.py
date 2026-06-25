import unittest
from pathlib import Path
from memory_os.core.config import MemoryOSConfig
from memory_os.ui.server import _find_federated_spaces

class TestBridges(unittest.TestCase):
    def test_bridges_import(self):
        # Even without the dependencies, importing the bridges shouldn't crash
        try:
            import memory_os.adapters.bridges.autogen_bridge
            import memory_os.adapters.bridges.crewai_bridge
            import memory_os.adapters.bridges.haystack_bridge
            import memory_os.adapters.bridges.llamaindex_bridge
            import memory_os.adapters.bridges.semantic_kernel_bridge
        except Exception as e:
            self.fail(f"Bridge import failed: {e}")

class TestFederatedUI(unittest.TestCase):
    def test_find_federated_spaces_no_crash(self):
        # We can test against our own directory
        cwd = Path(__file__).parent.resolve()
        spaces = _find_federated_spaces(cwd)
        # Should not crash and should return a list
        self.assertIsInstance(spaces, list)

if __name__ == '__main__':
    unittest.main()
