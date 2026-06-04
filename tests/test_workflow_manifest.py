import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from memory_os.toolkit.workflow_validator import build_report, write_manifest


class TestWorkflowManifest(unittest.TestCase):


    def test_missing_step_range_fails_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflows = root / "workflows"
            workflows.mkdir()
            (workflows / "chat.nano.toml").write_text(
                '\n'.join([
                    'id = "chat.nano"',
                    "step_min = 0",
                    "step_max = 2",
                    "level_min = 1",
                    "level_max = 18",
                    'model_policy = "cheap_free"',
                    'tools = ["search_memory"]',
                    'verification = ["schema_check"]',
                    "",
                ]),
                encoding="utf-8",
            )

            report = build_report(root)

            self.assertFalse(report["ok"])
            self.assertIn(13, report["missing_steps"])

    def test_write_manifest_outputs_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "memory" / "workflow_manifest.json"
            report = {
                "ok": True,
                "generated_at": "2026-06-02T00:00:00Z",
                "workflow_count": 0,
            }

            write_manifest(report, manifest)

            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["ok"], True)


if __name__ == "__main__":
    unittest.main()
