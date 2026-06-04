import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from scripts.validate_task_capsules import validate_file, validate_rows


def capsule(**overrides):
    row = {
        "timestamp": "2026-06-02T00:00:00Z",
        "task": "example",
        "files_modified": ["agent_context/HANDSHAKE.md"],
        "hurdles_regression": "none",
        "resolution": "done",
        "lessons_learned": "keep it small",
    }
    row.update(overrides)
    return row


class TestTaskCapsulesValidator(unittest.TestCase):
    def test_accepts_existing_capsule_shape_without_workflow_metadata(self):
        errors = validate_rows([json.dumps(capsule())])
        self.assertEqual(errors, [])

    def test_validates_optional_workflow_and_step_metadata(self):
        errors = validate_rows([
            json.dumps(capsule(workflow="memory_os", step_score=4, step_name="little")),
            json.dumps(capsule(workflow="unknown", step_score=13, step_name="huge")),
        ])

        self.assertEqual(len(errors), 3)
        self.assertIn("workflow must be product or memory_os", errors[0])
        self.assertIn("step_score must be an integer from 1 to 12", errors[1])
        self.assertIn("step_name is not in the 12-step scale", errors[2])

    def test_validate_file_reports_json_and_required_field_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task_capsules.jsonl"
            bad_row = capsule()
            del bad_row["resolution"]
            path.write_text("{bad json}\n" + json.dumps(bad_row) + "\n", encoding="utf-8")

            errors = validate_file(path)

        self.assertEqual(len(errors), 2)
        self.assertIn("invalid JSON", errors[0])
        self.assertIn("missing fields: resolution", errors[1])


if __name__ == "__main__":
    unittest.main()
