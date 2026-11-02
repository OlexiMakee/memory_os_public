import pytest
from memory_os.toolkit.console_parser import (
    get_parser,
    register_parser,
    BaseConsoleParser,
    ClaudeConsoleParser,
    CodexConsoleParser,
    AgyConsoleParser,
)

def test_base_parser_traceback():
    parser = BaseConsoleParser()
    text = (
        "some normal log\n"
        "Traceback (most recent call last):\n"
        "  File \"src/foo.py\", line 10, in main\n"
        "    run()\n"
        "  File \"src/foo.py\", line 5, in run\n"
        "    raise ValueError(\"invalid argument\")\n"
        "ValueError: invalid argument\n"
        "extra tail log"
    )
    res = parser.parse("unknown", text)
    assert res["last_error"] is not None
    assert "ValueError: invalid argument" in res["last_error"]
    assert "Traceback" in res["last_error"]


def test_base_parser_pytest():
    parser = BaseConsoleParser()
    text = (
        "running pytest...\n"
        "tests/test_foo.py .                                         [100%]\n"
        "280 passed, 2 failed in 7.89s\n"
    )
    res = parser.parse("unknown", text)
    assert res["pytest_summary"] == "280 passed, 2 failed in 7.89s"


def test_claude_parser_tool():
    parser = ClaudeConsoleParser()
    text1 = "Calling tool: replace_file_content with arguments:\n{}"
    assert parser.extract_tool(text1) == "replace_file_content"

    text2 = "replace_file_content(TargetFile='/path/to/file', Instruction='edit')"
    assert parser.extract_tool(text2) == "replace_file_content"


def test_codex_parser_tool():
    parser = CodexConsoleParser()
    text = "[codex] executing run_command on workspace"
    assert parser.extract_tool(text) == "run_command"


def test_agy_parser_tool():
    parser = AgyConsoleParser()
    text = "toolAction: 'Running command', toolSummary: 'Command execution'"
    assert parser.extract_tool(text) == "Running command"


def test_register_custom_parser():
    class CustomParser:
        def parse(self, agent_id: str, console_text: str):
            return {"agent_id": agent_id, "current_tool": "custom_magic"}

    register_parser("wizard", CustomParser())
    parser = get_parser("wizard")
    res = parser.parse("wizard", "abracadabra")
    assert res["current_tool"] == "custom_magic"


def test_interactive_prompts():
    parser = BaseConsoleParser()
    text = "Some output logs...\nDo you want to run this command? [y/N]"
    res = parser.parse("codex", text)
    assert res["interactive_question"] == "Do you want to run this command? [y/N]"
    assert res["suggested_answers"] == ["y", "n"]

    text2 = "Some output logs...\nProceed? [yes/no]: "
    res2 = parser.parse("claude", text2)
    assert "Proceed?" in res2["interactive_question"]
    assert res2["suggested_answers"] == ["yes", "no"]

    text3 = "Wait for action\nPress Enter to continue..."
    res3 = parser.parse("agy", text3)
    assert "Press Enter" in res3["interactive_question"]
    assert res3["suggested_answers"] == [""]


def test_interactive_option_menus():
    parser = BaseConsoleParser()
    text = (
        "Approaching rate limits\n"
        "Switch to gpt-5.4-mini for lower credit usage\n"
        "› 1. Switch to gpt-5.4-mini\n"
        "  2. Keep current model\n"
        "  3. Keep current model (never ask again)\n"
        "Press enter to confirm or esc to go back"
    )
    res = parser.parse("codex", text)
    assert "Press enter to confirm" in res["interactive_question"]
    assert res["suggested_answers"] == ["1", "2", "3"]


def test_limit_event_parsing_for_agy():
    parser = AgyConsoleParser()
    text = "working...\nYou've hit your usage limit. Try again at 11:28 AM."
    res = parser.parse("agy", text)
    assert res["limit_event"]["keyword"] == "usage limit"
    assert "Try again" in res["limit_event"]["line"]


def test_strict_limit_parsing_ignores_generic_rate_limit_discussion():
    parser = BaseConsoleParser()
    assert parser.extract_limit_event("Approaching rate limits soon", strict=True) is None
    assert parser.extract_limit_event("quota exceeded, again in 45m", strict=True)["keyword"] == "again in"


def test_limit_event_parsing_ignores_code_and_diffs():
    parser = BaseConsoleParser()
    # Code definition
    assert parser.extract_limit_event("def test_quota_monitor():") is None
    # Code assert
    assert parser.extract_limit_event("assert limit_seen > 0") is None
    # Quoted string literal
    assert parser.extract_limit_event('limit_text = "quota exceeded"') is None
    assert parser.extract_limit_event("'''try again at...'''") is None
    # Git diff lines
    assert parser.extract_limit_event("+quota exceeded, please wait") is None
    # Docstring/ellipses placeholder
    assert parser.extract_limit_event("in... ,  try again at... ).") is None


def test_limit_event_parsing_ignores_status_and_tui_lines():
    parser = BaseConsoleParser()
    # status line with dot separator
    assert parser.extract_limit_event("5h resets in 3h 57m  •  week resets in 131h 41m") is None
    # line containing agent-manager
    assert parser.extract_limit_event("Memory OS - Agent Manager status: rate limit active") is None
    # refreshes in line
    assert parser.extract_limit_event("31% remaining · Refreshes in 3h 58m") is None


