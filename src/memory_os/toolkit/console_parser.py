import re
from typing import Any, Dict, Optional, TypedDict, List, Protocol

class ParsedConsoleInfo(TypedDict, total=False):
    agent_id: str
    current_tool: Optional[str]
    last_error: Optional[str]
    pytest_summary: Optional[str]
    token_usage: Optional[Dict[str, int]]
    interactive_question: Optional[str]
    limit_event: Optional[Dict[str, Any]]


RATE_LIMIT_KEYWORDS = [
    "rate limit",
    "rate_limit",
    "rate-limit",
    "usage limit",
    "limit reached",
    "request limit",
    "daily limit",
    "try again at",
    "try again later",
    "resets in",
    "again in",
    "quota exceeded",
    "too many requests",
    "429",
    "credit balance zero",
    "insufficient quota",
    "billing",
]

STRICT_LIMIT_KEYWORDS = [
    "usage limit",
    "limit reached",
    "request limit",
    "daily limit",
    "try again at",
    "resets in",
    "again in",
    "quota exceeded",
    "too many requests",
    "429",
    "credit balance zero",
    "insufficient quota",
]

class ConsoleParser(Protocol):
    def parse(self, agent_id: str, console_text: str) -> ParsedConsoleInfo:
        ...

class BaseConsoleParser:
    """Base parser implementation using regular expressions (SOLID - Open/Closed principle).
    New specific agent parsers can inherit from this to specialize patterns or logic.
    """
    def __init__(self) -> None:
        # Matches typical Python tracebacks and error messages
        self.traceback_pattern = re.compile(
            r"(Traceback \(most recent call last\):.*?(?:\r?\n.*?)*\r?\n\w+Error:.*)", re.DOTALL
        )

    def extract_traceback(self, text: str) -> Optional[str]:
        # Extract the last Python traceback if present
        matches = list(self.traceback_pattern.finditer(text))
        if matches:
            tb = matches[-1].group(1).strip()
            # Truncate traceback to last 10 lines for brevity in status
            lines = tb.splitlines()
            if len(lines) > 10:
                return "\n".join(lines[-10:])
            return tb
        return None

    def extract_pytest_status(self, text: str) -> Optional[str]:
        # Extract the last pytest summary line
        lines = text.splitlines()
        for line in reversed(lines):
            # Check for passed line
            if " passed" in line and (" in " in line or " seconds" in line or "passed" in line):
                return line.strip()
            # Check for failed line
            if "failed" in line and ("failed" in line.lower() or "passed" in line):
                return line.strip()
            # Check for first failed test trace
            if line.startswith("FAILED tests/"):
                return line.strip()
        return None

    def extract_token_usage(self, text: str) -> Optional[Dict[str, int]]:
        # Match standard token usage outputs
        usage = {}
        prompt_m = re.search(r"(?:prompt_tokens|input_tokens)[:\s=]+(\d+)", text, re.IGNORECASE)
        completion_m = re.search(r"(?:completion_tokens|output_tokens)[:\s=]+(\d+)", text, re.IGNORECASE)
        if prompt_m:
            usage["prompt"] = int(prompt_m.group(1))
        if completion_m:
            usage["completion"] = int(completion_m.group(1))
        return usage if usage else None

    def parse(self, agent_id: str, console_text: str) -> ParsedConsoleInfo:
        return {
            "agent_id": agent_id,
            "current_tool": self.extract_tool(console_text),
            "last_error": self.extract_traceback(console_text),
            "pytest_summary": self.extract_pytest_status(console_text),
            "token_usage": self.extract_token_usage(console_text),
            "interactive_question": self.extract_question(console_text),
            "suggested_answers": self.extract_suggested_answers(console_text),
            "limit_event": self.extract_limit_event(console_text),
        }

    def extract_tool(self, text: str) -> Optional[str]:
        # Base implementation for generic tool execution
        lines = text.splitlines()
        for line in reversed(lines):
            m = re.search(
                r"(?:calling|running|invoking|execute)\s+(?:tool|command)?\s*[:`\'\"]*(\w+)[:`\'\"]*",
                line,
                re.IGNORECASE
            )
            if m:
                return m.group(1)
        return None

    def extract_question(self, text: str) -> Optional[str]:
        # Match standard interactive questions or confirmation prompts
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None
        # Check last 10 lines for a question, prompt, or selection menu
        for line in reversed(lines[-10:]):
            line_lower = line.lower()
            if "?" in line or any(p in line_lower for p in ("[y/n]", "(y/n)", "[y/n]:", "[yes/no]")):
                return line
            if "press enter" in line_lower or "press [enter]" in line_lower:
                return line
            if "rate limits" in line_lower or "select option" in line_lower or "switch to" in line_lower:
                return line
        return None

    def extract_suggested_answers(self, text: str) -> Optional[List[str]]:
        question = self.extract_question(text)
        if not question:
            return None
        question_lower = question.lower()
        if any(p in question_lower for p in ("[y/n]", "(y/n)", "[y/n]:")):
            return ["y", "n"]
        if "[yes/no]" in question_lower:
            return ["yes", "no"]
        # Find numbered options like "1.", "2." (possibly prefixed with list marker)
        options = re.findall(r"(?:^|\s|›)\s*(\d+)[\.\)]\s+", text)
        if options:
            return options
        if "press enter" in question_lower or "press [enter]" in question_lower:
            return [""]
        if "?" in question:
            return ["y", "n"]
        return None

    def extract_limit_event(self, text: str, strict: bool = False) -> Optional[Dict[str, Any]]:
        keywords = STRICT_LIMIT_KEYWORDS if strict else RATE_LIMIT_KEYWORDS
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            line_lower = line.lower()
            
            # Helper to check if a matched line is actually code or a test log
            def is_false_positive(l: str) -> bool:
                l_lower = l.lower()
                stripped = l.strip()
                
                # Check for quotes around the entire line or typical code syntax
                if (stripped.startswith('"') and (stripped.endswith('"') or stripped.endswith('",') or stripped.endswith('"+'))) or \
                   (stripped.startswith("'") and (stripped.endswith("'") or stripped.endswith("',") or stripped.endswith("'+"))):
                    return True
                
                # Common code/diff/test indicators
                code_indicators = [
                    "def ", "class ", "assert ", "self.", "import ", "from ",
                    "return ", "print(", "re.search", "re.compile", "mock_",
                    "fixtures", ".py", ".toml", ".json", "lambda ", "=== ", "--- ",
                    "unittest", "pytest", "logger.", "console_info", "limit_event",
                    "...", "keyword", "line", "try again at... )"
                ]
                if any(ind in l for ind in code_indicators):
                    return True
                
                # Check for git diff output lines or table rows
                if l.startswith(("+", "-", "@@")) or " | " in l or " • " in l:
                    return True
                    
                # Check for status/TUI reset lines
                if re.search(r"\b(?:5h|week|\d+h)\s+resets\s+in\b", l, re.IGNORECASE) or \
                   re.search(r"\brefreshes\s+in\s+\d+h\b", l, re.IGNORECASE) or \
                   "agent manager" in l_lower or "agent-manager" in l_lower:
                    return True

                # Check for assignment patterns
                compact = stripped.replace(" ", "")
                if '="' in compact or "='" in compact or '":' in compact:
                    return True
                    
                return False

            for keyword in keywords:
                if keyword in line_lower:
                    if is_false_positive(line):
                        continue
                    return {
                        "keyword": keyword,
                        "line": line,
                    }
        return None





class ClaudeConsoleParser(BaseConsoleParser):
    """Claude CLI specific output parser."""
    def extract_tool(self, text: str) -> Optional[str]:
        lines = text.splitlines()
        for line in reversed(lines):
            # Matches CLI calling tool line
            m = re.search(r"Calling tool:\s*(\w+)", line, re.IGNORECASE)
            if m:
                return m.group(1)
            # Matches function call with arguments like replace_file_content(...)
            m2 = re.search(r"(\w+)\((?:TargetFile|AbsolutePath|Cwd|CommandLine)=", line)
            if m2:
                return m2.group(1)
        return super().extract_tool(text)


class CodexConsoleParser(BaseConsoleParser):
    """Codex specific output parser."""
    def extract_tool(self, text: str) -> Optional[str]:
        lines = text.splitlines()
        for line in reversed(lines):
            m = re.search(r"\[codex\]\s+(?:executing|running|calling)\s+(\w+)", line, re.IGNORECASE)
            if m:
                return m.group(1)
        return super().extract_tool(text)


class AgyConsoleParser(BaseConsoleParser):
    """Antigravity (AGY) specific output parser."""
    def extract_tool(self, text: str) -> Optional[str]:
        lines = text.splitlines()
        for line in reversed(lines):
            # AGY toolAction log pattern
            m = re.search(r"toolAction:\s*['\"]([^'\"]+)['\"]", line, re.IGNORECASE)
            if m:
                return m.group(1)
            m2 = re.search(r"Calling tool:\s*(\w+)", line, re.IGNORECASE)
            if m2:
                return m2.group(1)
        return super().extract_tool(text)


# Registry of parsers (Open/Closed Principle)
_PARSERS: Dict[str, ConsoleParser] = {
    "claude": ClaudeConsoleParser(),
    "codex": CodexConsoleParser(),
    "agy": AgyConsoleParser(),
}

def register_parser(agent_id: str, parser: ConsoleParser) -> None:
    """Register a new parser for a custom agent (Open/Closed Principle)."""
    _PARSERS[agent_id.lower()] = parser

def get_parser(agent_id: str) -> ConsoleParser:
    """Retrieve the registered parser or default to BaseConsoleParser."""
    return _PARSERS.get(agent_id.lower(), BaseConsoleParser())
