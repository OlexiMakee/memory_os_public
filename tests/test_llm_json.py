import pytest

from memory_os.core.llm_json import strip_json_code_fence


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (' {"ok":true} ', '{"ok":true}'),
        ('```json\n{"ok":true}\n```', '{"ok":true}'),
        ('```\n{"ok":true}\n```\n\n', '{"ok":true}'),
        ('```json\n{"ok":true}', '{"ok":true}'),
    ],
)
def test_strip_json_code_fence(raw, expected):
    assert strip_json_code_fence(raw) == expected
