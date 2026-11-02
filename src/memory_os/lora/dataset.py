import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import confine_to_root
from memory_os.llm.types import ChatMessage
from memory_os.lora.types import ToolCallExample


class ExampleSource(ABC):
    """A pluggable source of training examples for one skill adapter."""

    @abstractmethod
    def examples(self) -> Iterable[ToolCallExample]:
        ...


class CapsuleToolCallSource(ExampleSource):
    """Turns agent_context/task_capsules.jsonl entries with an 'action' field
    into tool-call examples — the basis for a 'memory'/'terminal'-style
    skill adapter that learns this project's own tool-calling conventions."""

    def __init__(self, config: MemoryOSConfig, system_prompt: str):
        self.config = config
        self.system_prompt = system_prompt

    def examples(self) -> Iterable[ToolCallExample]:
        path = self.config.capsules_file
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    capsule = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tool_call = self._capsule_to_tool_call(capsule)
                if tool_call is None:
                    continue
                yield ToolCallExample(
                    messages=[
                        ChatMessage(role="system", content=self.system_prompt),
                        ChatMessage(
                            role="user",
                            content=capsule.get("task") or capsule.get("summary", ""),
                        ),
                    ],
                    tool_call=tool_call,
                    source=f"capsule:{capsule.get('id', '?')}",
                )

    @staticmethod
    def _capsule_to_tool_call(capsule: dict) -> Optional[dict]:
        action = capsule.get("action")
        if not action:
            return None
        return {"name": action, "arguments": capsule.get("arguments", {})}


class SqliteGraphSource(ExampleSource):
    """
    Turns verified nodes already mirrored into memory_os.db (via 'memory_os
    sync') into examples of this project's own propose_node tool call —
    not a new datastore, just the SQLite mirror Memory OS already
    maintains. Only 'verified' nodes are used (they already passed
    LifecycleManager.transition()'s schema/evidence checks), so the dataset
    only encodes facts the project itself has already accepted as correct.

    Ordered by access_count descending by default, so frequently-retrieved
    memories — the ones actually load-bearing for this agent's day-to-day
    work — dominate the adapter's training signal over rarely-touched ones.
    """

    def __init__(self, config: MemoryOSConfig, system_prompt: str, min_access_count: int = 0):
        self.config = config
        self.system_prompt = system_prompt
        self.min_access_count = min_access_count

    def examples(self) -> Iterable[ToolCallExample]:
        from memory_os.core.core import MemoryOS

        db = MemoryOS(self.config)
        conn = db.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, type, summary, tags, access_count FROM graph_nodes
                WHERE status = 'verified' AND access_count >= ?
                ORDER BY access_count DESC
                """,
                (self.min_access_count,),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            tags = [t for t in (row["tags"] or "").split(",") if t]
            yield ToolCallExample(
                messages=[
                    ChatMessage(role="system", content=self.system_prompt),
                    ChatMessage(role="user", content=f"Remember this: {row['summary']}"),
                ],
                tool_call={
                    "name": "propose_node",
                    "arguments": {
                        "id": row["id"],
                        "type": row["type"],
                        "summary": row["summary"],
                        "tags": tags,
                    },
                },
                source=f"sqlite_node:{row['id']}",
            )


class LocalDocumentSource(ExampleSource):
    """
    Turns local files already on this machine (e.g. your own security audit
    notes, DEV_STRATEGY.md, raw incident logs) into instruction-following
    examples for a local document-processing adapter.

    Reads content verbatim, with no redaction — appropriate ONLY because
    these are private documents that already never leave this machine (see
    .gitattributes export-ignore in this project). This builds training data
    for a model that processes content locally instead of refusing/softening
    it the way a cloud provider's content policy might; it is not a tool for
    stripping safety behavior around harmful content categories. Only point
    this at documents you are authorized to process.
    """

    def __init__(
        self,
        root_dir: Path,
        glob_patterns: List[str],
        instruction: str,
        system_prompt: str,
    ):
        self.root_dir = Path(root_dir)
        self.glob_patterns = glob_patterns
        self.instruction = instruction
        self.system_prompt = system_prompt

    def examples(self) -> Iterable[ToolCallExample]:
        for pattern in self.glob_patterns:
            for path in sorted(self.root_dir.glob(pattern)):
                if not path.is_file():
                    continue
                resolved = confine_to_root(str(path), self.root_dir)
                text = resolved.read_text(encoding="utf-8", errors="ignore").strip()
                if not text:
                    continue
                yield ToolCallExample(
                    messages=[
                        ChatMessage(role="system", content=self.system_prompt),
                        ChatMessage(
                            role="user",
                            content=f"{self.instruction}\n\n---\n{text}",
                        ),
                    ],
                    source=f"doc:{resolved.relative_to(self.root_dir)}",
                )


class ActionRouterSource(ExampleSource):
    """
    Hand-curated SFT examples for the role=action adapter.

    Each example replicates the EXACT prompt format that LocalLLMActionBrain
    builds at inference time (task / available_actions / routing_hints /
    argument_hints / answer_format blocks) so the adapter trains on what it
    will see when deployed.

    Responses are ground-truth JSON — do NOT replace with model-generated
    completions without manual verification; auto-generated training data
    defeats the point of a deterministic action-router.
    """

    _VOCAB_BLOCK = (
        "<available_actions>\n"
        "file.read: Read one local file by path, confined to the project root.\n"
        "memory.search: Search the memory graph (FTS5 + graph traversal).\n"
        "memory.write: Propose a new memory node (lands as draft, not verified).\n"
        "</available_actions>"
    )
    _ROUTING_HINTS = (
        "<routing_hints>\n"
        "- Use memory.write when the task asks to remember, store, save, record, add, or learn a new rule/fact.\n"
        "- Use memory.search when the task asks to find, search, recall, or inspect existing memory.\n"
        "- Use file.read when the task asks to read, show, open, or display a project file.\n"
        "</routing_hints>"
    )
    _ARG_HINTS = (
        "<argument_hints>\n"
        '- memory.search args: {"query": string}.\n'
        '- memory.write args: {"summary": string, "type": "rule"|"fact"}. Do not leave summary empty.\n'
        '- file.read args: {"path": string}.\n'
        "</argument_hints>"
    )
    _ANSWER_FORMAT = (
        "<answer_format>\n"
        'Respond with exactly one JSON object: {"action": "<name>", "args": {...}}. No other text.\n'
        "</answer_format>"
    )

    # (task, action, args)
    _EXAMPLES = [
        # ── memory.search ──────────────────────────────────────────────────
        ("Find anything we know about force-push safety rules.", "memory.search", {"query": "force-push safety rules"}),
        ("Search memory for notes about the LoRA training venv setup.", "memory.search", {"query": "LoRA training venv"}),
        ("What do we know about Qwen3.5 base model behavior?", "memory.search", {"query": "Qwen3.5 base model"}),
        ("Recall any notes about llama.cpp integration.", "memory.search", {"query": "llama.cpp integration"}),
        ("Find what we've stored about Python 3.14 compatibility issues.", "memory.search", {"query": "Python 3.14 compatibility"}),
        ("Look up any notes on Ollama Docker container setup.", "memory.search", {"query": "Ollama Docker"}),
        ("Search for notes about the eval runner implementation.", "memory.search", {"query": "eval runner"}),
        ("What have we recorded about agent action routing?", "memory.search", {"query": "agent action routing"}),
        ("Find notes on Ubuntu hardening procedures.", "memory.search", {"query": "Ubuntu hardening"}),
        ("Look up anything about swarm mode orchestration.", "memory.search", {"query": "swarm mode orchestration"}),
        ("Recall what we know about Telegram chatbot training.", "memory.search", {"query": "Telegram chatbot training"}),
        ("Search for information about the RTX 3060 Ti CUDA setup.", "memory.search", {"query": "RTX 3060 Ti CUDA"}),
        ("What do we know about trl SFT trainer column format?", "memory.search", {"query": "trl SFT trainer"}),
        ("Find notes about git commit hooks.", "memory.search", {"query": "git commit hooks"}),
        ("Look up any stored rules about code review practices.", "memory.search", {"query": "code review"}),
        ("Search memory for notes about the action-router SFT dataset.", "memory.search", {"query": "action-router SFT dataset"}),
        ("Find everything recorded about Memory OS architecture.", "memory.search", {"query": "Memory OS architecture"}),
        ("Recall what we stored about the daemon IPC protocol.", "memory.search", {"query": "daemon IPC"}),
        # ── memory.write ───────────────────────────────────────────────────
        ("Remember this rule: always run tests before committing.", "memory.write", {"summary": "always run tests before committing", "type": "rule"}),
        ("Save this fact: Python 3.14 breaks dill due to pickle internals change.", "memory.write", {"summary": "Python 3.14 breaks dill due to pickle internals change", "type": "fact"}),
        ("Store this rule: never force-push to main without approval.", "memory.write", {"summary": "never force-push to main without approval", "type": "rule"}),
        ("Record this fact: Qwen3.5-4B-Base GGUF is stored at /home/oleksii/models/gguf/.", "memory.write", {"summary": "Qwen3.5-4B-Base GGUF is at /home/oleksii/models/gguf/", "type": "fact"}),
        ("Learn this: llama-completion -no-cnv must be used for base models to avoid chat template injection.", "memory.write", {"summary": "use llama-completion -no-cnv for base models to avoid chat template injection", "type": "rule"}),
        ("Save the fact that the training venv uses Python 3.12, not 3.14.", "memory.write", {"summary": "training venv uses Python 3.12 not 3.14", "type": "fact"}),
        ("Remember: agy flags must be placed before --print in shell invocations.", "memory.write", {"summary": "agy flags must be placed before --print in shell", "type": "rule"}),
        ("Add this rule: always verify swarm worker output with git status.", "memory.write", {"summary": "always verify swarm output with git status", "type": "rule"}),
        ("Store this: the RTX 3060 Ti runs CUDA 13.2 with driver 595.71.05.", "memory.write", {"summary": "RTX 3060 Ti uses CUDA 13.2 driver 595.71.05", "type": "fact"}),
        ("Note this: do not give agent CLIs --add-dir to private repo without explicit consent.", "memory.write", {"summary": "do not give agent CLIs --add-dir to private repo without consent", "type": "rule"}),
        ("Record this fact: trl 0.24.0 does not auto-handle the messages column.", "memory.write", {"summary": "trl 0.24.0 does not auto-handle messages column", "type": "fact"}),
        ("Remember: Telegram chatbot LoRA and action-router LoRA must stay as separate adapters.", "memory.write", {"summary": "keep Telegram chatbot LoRA and action-router LoRA separate", "type": "rule"}),
        ("Save that gemma3:4b passes agent-action-validity 5/5 on Ollama.", "memory.write", {"summary": "gemma3:4b passes agent-action-validity 5/5 on Ollama", "type": "fact"}),
        ("Learn this rule: do not hardcode model names; use discovery or env vars.", "memory.write", {"summary": "do not hardcode model names; use discovery or env vars", "type": "rule"}),
        ("Record: Qwen3.5-4B-Base with JSON schema returns correct action and args.", "memory.write", {"summary": "Qwen3.5-4B-Base with JSON schema returns correct action and args", "type": "fact"}),
        ("Remember: the main venv is .venv (Python 3) and the train venv is .venv-train (Python 3.12).", "memory.write", {"summary": ".venv is main venv, .venv-train is training venv (Python 3.12)", "type": "fact"}),
        ("Save the rule: always strip [end of text] EOS markers from llama.cpp output before JSON parsing.", "memory.write", {"summary": "strip [end of text] and EOS markers from llama.cpp output before JSON parsing", "type": "rule"}),
        ("Record this: LLAMA_CPP_MODEL env var controls which GGUF the llama_cpp provider uses.", "memory.write", {"summary": "LLAMA_CPP_MODEL env var selects the GGUF for llama_cpp provider", "type": "fact"}),
        ("Store this fact: codex exec defaults to read-only sandbox; use --sandbox workspace-write for file writes.", "memory.write", {"summary": "codex requires --sandbox workspace-write for file writes", "type": "fact"}),
        ("Save: unsloth re-pins torch to cu128; do not fight the resolver.", "memory.write", {"summary": "unsloth re-pins torch to cu128; do not fight the resolver", "type": "fact"}),
        ("Add a rule: commit only when explicitly asked; never proactively commit.", "memory.write", {"summary": "commit only when explicitly asked; never proactively commit", "type": "rule"}),
        # Extra "Remember…" examples to reinforce write-not-search for this phrasing:
        ("Remember this rule: always run the test suite before committing.", "memory.write", {"summary": "always run the test suite before committing", "type": "rule"}),
        ("Remember this rule: never merge without a passing CI run.", "memory.write", {"summary": "never merge without a passing CI run", "type": "rule"}),
        ("Remember this rule: use absolute imports inside the src/ package.", "memory.write", {"summary": "use absolute imports inside src/", "type": "rule"}),
        ("Remember this fact: the action_router adapter v001 achieves pass_rate=0.80 on agent-action-validity.", "memory.write", {"summary": "action_router v001 pass_rate=0.80 on agent-action-validity", "type": "fact"}),
        ("Remember: LLAMA_CPP_LORA env var points to the LoRA adapter GGUF for llama-completion.", "memory.write", {"summary": "LLAMA_CPP_LORA env var points to LoRA adapter GGUF for llama-completion", "type": "fact"}),
        ("Remember: convert_lora_to_gguf.py converts PEFT LoRA safetensors to llama.cpp-compatible GGUF.", "memory.write", {"summary": "convert_lora_to_gguf.py converts PEFT LoRA to llama.cpp GGUF format", "type": "fact"}),
        ("Remember this: Qwen3.5 thinking mode emits </think> before the JSON answer; strip it in the provider.", "memory.write", {"summary": "Qwen3.5 thinking mode emits </think> before JSON; strip before parsing", "type": "fact"}),
        ("Remember: the hf CLI replaced huggingface-cli; use hf download, not huggingface-cli download.", "memory.write", {"summary": "use hf download instead of deprecated huggingface-cli download", "type": "rule"}),
        # ── file.read ──────────────────────────────────────────────────────
        ("Show me the contents of README.md.", "file.read", {"path": "README.md"}),
        ("Open src/memory_os/core/llm_service.py and show its content.", "file.read", {"path": "src/memory_os/core/llm_service.py"}),
        ("Display the file agent_context/HANDSHAKE.md.", "file.read", {"path": "agent_context/HANDSHAKE.md"}),
        ("Read src/memory_os/agent_brain/brain.py.", "file.read", {"path": "src/memory_os/agent_brain/brain.py"}),
        ("Show me scripts/swarm_invoke.py.", "file.read", {"path": "scripts/swarm_invoke.py"}),
        ("What is in data/lora/docs.jsonl?", "file.read", {"path": "data/lora/docs.jsonl"}),
        ("Read the file src/memory_os/toolkit/eval_runner.py.", "file.read", {"path": "src/memory_os/toolkit/eval_runner.py"}),
        ("Display agent_context/CONSTITUTION.md.", "file.read", {"path": "agent_context/CONSTITUTION.md"}),
        ("Show me src/memory_os/lora/training_config.py.", "file.read", {"path": "src/memory_os/lora/training_config.py"}),
        ("Open and display src/memory_os/core/config.py.", "file.read", {"path": "src/memory_os/core/config.py"}),
        ("Read .gitignore.", "file.read", {"path": ".gitignore"}),
        ("Show the file src/memory_os/toolkit/evals/agent-action-validity/cases.jsonl.", "file.read", {"path": "src/memory_os/toolkit/evals/agent-action-validity/cases.jsonl"}),
    ]

    def _build_prompt(self, task: str) -> str:
        return (
            f"<task>\n{task}\n</task>\n"
            f"{self._VOCAB_BLOCK}\n"
            f"{self._ROUTING_HINTS}\n"
            f"{self._ARG_HINTS}\n"
            f"{self._ANSWER_FORMAT}"
        )

    def examples(self) -> Iterable[ToolCallExample]:
        import json as _json
        for task, action, args in self._EXAMPLES:
            yield ToolCallExample(
                messages=[
                    ChatMessage(role="user", content=self._build_prompt(task)),
                    ChatMessage(
                        role="assistant",
                        content=_json.dumps({"action": action, "args": args}, ensure_ascii=False),
                    ),
                ],
                tool_call=None,  # raw JSON completion, not tool-call format
                source=f"action_router_curated:{action}",
            )


class TelegramToolCallSource(ExampleSource):
    """
    Converts real Telegram conversation records into action-router SFT rows.

    Newer conversation logs store original ActionRequest arguments as
    action_args. Older logs are still usable when arguments can be
    reconstructed deterministically from the user's message.
    """

    _SUPPORTED_ACTIONS = {"memory.search", "memory.write", "file.read"}
    _PATH_RE = re.compile(r"(?P<path>(?:[\w.-]+/)+[\w.-]+|[\w.-]+\.[A-Za-z0-9_]+)")

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.prompt_builder = ActionRouterSource()

    def examples(self) -> Iterable[ToolCallExample]:
        path = self.config.root_dir / "agent_context" / "telegram_conversations.jsonl"
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                example = self._record_to_example(record, line_no)
                if example is not None:
                    yield example

    def _record_to_example(self, record: dict, line_no: int) -> Optional[ToolCallExample]:
        action = record.get("action")
        if action not in self._SUPPORTED_ACTIONS:
            return None
        text = str(record.get("user_text") or "").strip()
        if not text:
            return None
        args = record.get("action_args") if isinstance(record.get("action_args"), dict) else None
        if args is None:
            args = self._args_for_action(action, text)
        if args is None:
            return None
        update_id = record.get("update_id", "?")
        message_id = record.get("message_id", line_no)
        return ToolCallExample(
            messages=[
                ChatMessage(role="user", content=self.prompt_builder._build_prompt(text)),
                ChatMessage(
                    role="assistant",
                    content=json.dumps({"action": action, "args": args}, ensure_ascii=False),
                ),
            ],
            tool_call=None,
            source=f"telegram:{update_id}:{message_id}",
        )

    def _args_for_action(self, action: str, text: str) -> Optional[dict]:
        if action == "memory.search":
            return {"query": text}
        if action == "memory.write":
            return {"summary": self._memory_summary(text), "type": self._memory_type(text)}
        if action == "file.read":
            match = self._PATH_RE.search(text)
            if not match:
                return None
            return {"path": match.group("path")}
        return None

    @staticmethod
    def _memory_summary(text: str) -> str:
        cleaned = re.sub(
            r"^\s*(запам'ятай|запамятай|збережи|запиши|зафіксуй|store this|save this|note this|remember this)\s*[:,-]?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        return cleaned or text

    @staticmethod
    def _memory_type(text: str) -> str:
        lowered = text.lower()
        if any(marker in lowered for marker in ("rule", "правило", "завжди", "ніколи", "always", "never")):
            return "rule"
        return "fact"


_UK_RESPONDER_SYSTEM_PROMPT = (
    "Ти — автономний асистент пам'яті Memory OS.\n"
    "ТВОЄ ПЕРШЕ І ГОЛОВНЕ ПРАВИЛО: БЕЗАПЕЛЯЦІЙНЕ ЗВЕРНЕННЯ ДО ТУЛЗІВ ТА СТРУКТУРОВАНІ ВІДПОВІДІ.\n"
    "Якщо запит вимагає інформації або дії — завжди використовуй інструменти (memory.search, memory.write, swarm.dispatch).\n"
    "Повертай результати коротко, детерміновано і природньою українською мовою. Ніколи не вигадуй фактів."
)

UK_RESPONDER_SYSTEM_PROMPT = _UK_RESPONDER_SYSTEM_PROMPT


class UkrainianResponderSource(ExampleSource):
    """
    Hand-curated SFT examples for the role=responder Ukrainian adapter.

    Each example reproduces what LocalLLMResponder.respond() receives at inference:
      system = UK_RESPONDER_SYSTEM_PROMPT
      user   = "Task: {task}\\nAction: {action}\\nResult: {outcome}"
             OR direct conversational message for "chat" action (no tool result)
      assistant = natural Ukrainian reply

    Training examples cover:
    - Action result formatting (memory.search / memory.write / file.read outcomes)
    - Graceful error messages in Ukrainian
    - Conversational: greetings, capability questions, small talk, boundaries
    - Ukrainian idioms and short commands

    Ground-truth responses must be natural Ukrainian — do NOT auto-generate
    without manual review; hallucinated or poor-quality answers corrupt the adapter.
    """

    # (task, action, outcome, ukrainian_response)
    _EXAMPLES = [
        # ─────────────────────────────────────────────────────────────────
        # memory.search — results found
        # ─────────────────────────────────────────────────────────────────
        (
            "Знайди що ми знаємо про llama.cpp",
            "memory.search",
            "Found 2 nodes: [llama.cpp provider uses LLAMA_CPP_MODEL env var | use -no-cnv for base models]",
            "Знайшов 2 нотатки про llama.cpp:\n• Провайдер визначається через LLAMA_CPP_MODEL\n• Для базових моделей потрібен прапор -no-cnv",
        ),
        (
            "Пошукай правила щодо git комітів",
            "memory.search",
            "Found 3 nodes: [commit only when explicitly asked | never force-push to main | run tests before committing]",
            "Знайшов 3 правила щодо git:\n• Комітити тільки за явним запитом\n• Ніколи не force-push до main\n• Запускати тести перед комітом",
        ),
        (
            "Що ми зберігали про RTX 3060 Ti?",
            "memory.search",
            "Found 1 node: [RTX 3060 Ti uses CUDA 13.2 driver 595.71.05]",
            "Знайшов одну нотатку:\n• RTX 3060 Ti — CUDA 13.2, драйвер 595.71.05",
        ),
        (
            "Знайди нотатки про LoRA тренування",
            "memory.search",
            "Found 4 nodes: [training venv uses Python 3.12 | unsloth re-pins torch to cu128 | trl 0.24.0 messages column fix | action_router v002 pass_rate=0.80]",
            "Знайшов 4 нотатки про LoRA:\n• venv тренування — Python 3.12\n• unsloth перепинає torch до cu128\n• trl 0.24.0 потребує flatten messages → text\n• action_router v002: pass_rate=0.80",
        ),
        (
            "Знайди все що знаємо про Ollama",
            "memory.search",
            "Found 2 nodes: [Ollama Docker container ollama-memoryos at localhost:11434 | gemma3:4b passes eval 5/5]",
            "Знайшов 2 нотатки про Ollama:\n• Контейнер ollama-memoryos на localhost:11434\n• gemma3:4b проходить eval 5/5",
        ),
        (
            "Пошукай правила безпеки агентів",
            "memory.search",
            "Found 2 nodes: [do not give agent CLIs --add-dir to private repo without consent | commit only when explicitly asked]",
            "Знайшов 2 правила безпеки:\n• Не давати агентам --add-dir до приватного репо без дозволу\n• Комітити тільки за явним запитом",
        ),
        (
            "Шукай інформацію про eval runner",
            "memory.search",
            "Found 1 node: [agent-action-validity eval has 5 cases, pass_threshold=0.66]",
            "Знайшов:\n• Eval agent-action-validity: 5 кейсів, поріг pass_rate=0.66",
        ),
        (
            "Знайди нотатки про Python 3.14",
            "memory.search",
            "Found 1 node: [Python 3.14 breaks dill due to pickle internals change]",
            "Знайшов:\n• Python 3.14 ламає dill через зміни у pickle internals",
        ),
        (
            "Знайди правила про код ревью",
            "memory.search",
            "Found 1 node: [never merge without a passing CI run]",
            "Знайшов одне правило:\n• Не мерджити без успішного CI",
        ),
        (
            "Що зберігали про docker?",
            "memory.search",
            "Found 1 node: [Ollama Docker container ollama-memoryos at http://localhost:11434]",
            "Знайшов:\n• Docker контейнер Ollama — ollama-memoryos, http://localhost:11434",
        ),
        (
            "Шукай нотатки про venv",
            "memory.search",
            "Found 2 nodes: [main venv is .venv Python 3 | training venv is .venv-train Python 3.12]",
            "Знайшов 2 нотатки:\n• .venv — основний, Python 3\n• .venv-train — тренувальний, Python 3.12",
        ),
        (
            "Знайди все про agy CLI",
            "memory.search",
            "Found 1 node: [agy flags must be placed before --print in shell]",
            "Знайшов:\n• Прапори agy треба ставити ДО --print у shell",
        ),
        (
            "Пошукай нотатки про Memory OS архітектуру",
            "memory.search",
            "Found 3 nodes: [provider chain llama_cpp → ollama → gemini → groq | .env auto-loaded by cli.py | LLAMA_CPP_LORA points to adapter GGUF]",
            "Знайшов 3 нотатки про архітектуру:\n• Ланцюжок: llama_cpp → ollama → gemini → groq\n• .env автозавантажується через cli.py\n• LLAMA_CPP_LORA вказує на GGUF адаптера",
        ),
        # ─────────────────────────────────────────────────────────────────
        # memory.search — nothing found
        # ─────────────────────────────────────────────────────────────────
        (
            "Що ми знаємо про Telegram адаптер?",
            "memory.search",
            "No results found.",
            "Нічого не знайшов за цим запитом. Можливо, ще не зберігали нотаток про Telegram адаптер.",
        ),
        (
            "Пошукай усі факти про GPU памʼять",
            "memory.search",
            "No results found.",
            "Не знайшов нотаток за цим запитом. Спробуй уточнити — наприклад «RTX 3060 Ti» або «VRAM».",
        ),
        # ─────────────────────────────────────────────────────────────────
        # memory.write — success
        # ─────────────────────────────────────────────────────────────────
        (
            "Запам'ятай це правило: завжди запускати тести перед комітом",
            "memory.write",
            "Memory node draft created: node_20260628_001 (status=draft, type=rule)",
            "Записав. Правило у чернетці — після перевірки стане активним.",
        ),
        (
            "Збережи факт: RTX 3060 Ti підтримує CUDA 13.2",
            "memory.write",
            "Memory node draft created: node_20260628_002 (status=draft, type=fact)",
            "Збережено. Факт про RTX 3060 Ti у чернетці.",
        ),
        (
            "Запам'ятай: llama.cpp потребує -no-cnv для базових моделей",
            "memory.write",
            "Memory node draft created: node_20260628_003 (status=draft, type=rule)",
            "Записав правило про -no-cnv. Чекає перевірки.",
        ),
        (
            "Запиши правило: ніколи не force-push до main",
            "memory.write",
            "Memory node draft created: node_20260628_004 (status=draft, type=rule)",
            "Готово. Правило щодо force-push записано.",
        ),
        (
            "Зафіксуй факт: action_router v002 pass_rate = 0.80",
            "memory.write",
            "Memory node draft created: node_20260628_005 (status=draft, type=fact)",
            "Зафіксовано: action_router v002, pass_rate=0.80. Нотатка у чернетці.",
        ),
        (
            "Запам'ятай що codex потребує --sandbox workspace-write для запису файлів",
            "memory.write",
            "Memory node draft created: node_20260628_006 (status=draft, type=fact)",
            "Записав. Факт про codex --sandbox у чернетці.",
        ),
        (
            "Зафіксуй: hf download замінює huggingface-cli",
            "memory.write",
            "Memory node draft created: node_20260628_007 (status=draft, type=rule)",
            "Готово. Правило про hf CLI збережено.",
        ),
        (
            "Збережи порожню нотатку",
            "memory.write",
            "Error: summary field is empty",
            "Не вдалося зберегти — текст нотатки порожній. Уточни що саме записати.",
        ),
        # ─────────────────────────────────────────────────────────────────
        # file.read results
        # ─────────────────────────────────────────────────────────────────
        (
            "Покажи README.md",
            "file.read",
            "File content (README.md, 847 bytes): # Memory OS\nLocal-first persistent memory graph...",
            "Ось README.md (847 байт):\n\n# Memory OS\nLocal-first persistent memory graph…",
        ),
        (
            "Прочитай .env файл",
            "file.read",
            "Error: path '.env' is in the export-ignore list and cannot be read",
            "Файл .env захищено від читання — він містить секрети. Це очікувана поведінка.",
        ),
        (
            "Відкрий agent_context/HANDSHAKE.md",
            "file.read",
            "File content (HANDSHAKE.md, 2.1 KB): # Active Handoff\n...",
            "Ось HANDSHAKE.md (2.1 КБ):\n\n# Active Handoff\n…",
        ),
        (
            "Покажи pyproject.toml",
            "file.read",
            "File content (pyproject.toml, 1.8 KB): [project]\nname = \"memory_os\"\nversion = \"0.1.0\"...",
            "Ось pyproject.toml:\n\n[project]\nname = \"memory_os\"\nversion = \"0.1.0\"\n…",
        ),
        (
            "Прочитай файл що не існує",
            "file.read",
            "Error: file not found: nonexistent.md",
            "Файл не знайдено: nonexistent.md. Перевір шлях.",
        ),
        (
            "Відкрий src/memory_os/core/config.py",
            "file.read",
            "File content (config.py, 3.4 KB): from dataclasses import dataclass...",
            "Ось config.py (3.4 КБ):\n\nfrom dataclasses import dataclass\n…",
        ),
        (
            "Покажи scripts/swarm_invoke.py",
            "file.read",
            "Error: file not found: scripts/swarm_invoke.py",
            "Файл scripts/swarm_invoke.py не знайдено. Можливо, перейменований або не існує.",
        ),
        (
            "Відкрий .gitignore",
            "file.read",
            "File content (.gitignore, 512 bytes): # Build artifacts\n__pycache__/\n*.pyc...",
            "Ось .gitignore (512 байт):\n\n# Build artifacts\n__pycache__/\n*.pyc\n…",
        ),
        # ─────────────────────────────────────────────────────────────────
        # Action errors / system failures
        # ─────────────────────────────────────────────────────────────────
        (
            "Знайди нотатки",
            "memory.search",
            "Error: database is locked, try again shortly",
            "База тимчасово заблокована. Спробуй за кілька секунд.",
        ),
        (
            "Запам'ятай правило",
            "memory.write",
            "Error: storage quota exceeded (disk usage at 95%)",
            "Помилка збереження — диск майже заповнено (95%). Потрібно звільнити місце або запустити compact.",
        ),
        (
            "Виконай пошук",
            "memory.search",
            "Error: LLM provider unavailable, no API key configured",
            "Немає доступного LLM-провайдера. Перевір API ключі або запусти Ollama локально.",
        ),
        (
            "Прочитай файл",
            "file.read",
            "Error: path traversal detected, access denied",
            "Доступ заблоковано — шлях виходить за межі проекту. Читати можна лише файли у проекті.",
        ),
        (
            "Знайди нотатки",
            "memory.search",
            "Error: search index not built, run 'memory_os sync' first",
            "Індекс пошуку не побудовано. Запусти `memory_os sync` для індексації пам'яті.",
        ),
        (
            "Збережи нотатку",
            "memory.write",
            "Error: timeout after 30s",
            "Операція перевищила час очікування (30с). Спробуй ще раз або перевір стан сховища.",
        ),
        (
            "Зроби щось",
            "chat",
            "Error: action 'unknown' is not supported",
            "Не зрозумів що треба зробити. Уточни: «Знайди...», «Запам'ятай...» або «Покажи файл...».",
        ),
        (
            "Ну зроби",
            "chat",
            "",
            "Зрозумів, але не зрозумів що саме :) Скажи точніше — що шукати, зберегти або показати.",
        ),
        # ─────────────────────────────────────────────────────────────────
        # Pure conversational: greetings / farewell
        # ─────────────────────────────────────────────────────────────────
        ("Привіт!", "chat", "", "Привіт! Що треба знайти або запам'ятати?"),
        ("Добрий день", "chat", "", "Добрий день! Чим можу допомогти?"),
        ("Доброго ранку!", "chat", "", "Доброго ранку! Готовий до роботи."),
        ("Добрий вечір", "chat", "", "Добрий вечір! Чим можу бути корисним?"),
        ("До побачення", "chat", "", "До побачення! Звертайся будь-коли."),
        ("Бувай", "chat", "", "Бувай! Гарного дня."),
        ("Дякую за допомогу", "chat", "", "Будь ласка! Радий був допомогти."),
        ("Дуже дякую", "chat", "", "Завжди радий. Якщо ще щось потрібно — я тут."),
        # ─────────────────────────────────────────────────────────────────
        # Pure conversational: capability questions
        # ─────────────────────────────────────────────────────────────────
        (
            "Що ти вмієш?",
            "chat", "",
            "Зберігаю нотатки, правила і факти, шукаю їх за запитом і читаю файли проекту. "
            "Пиши: «Запам'ятай...», «Знайди...» або «Покажи файл...».",
        ),
        (
            "Чим ти можеш допомогти?",
            "chat", "",
            "Можу зберегти нотатку, знайти що ми вже знаємо, або прочитати файл. Все локально.",
        ),
        (
            "Як тебе використовувати?",
            "chat", "",
            "Пиши природньою мовою: «Запам'ятай це правило...», «Знайди нотатки про...», «Покажи .gitignore». Я розберу і зроблю.",
        ),
        (
            "Ти розумієш українську?",
            "chat", "",
            "Так, відповідаю українською. Питай.",
        ),
        (
            "Що таке Memory OS?",
            "chat", "",
            "Memory OS — локальний граф пам'яті. Зберігає нотатки, правила, факти; дає пошук та lifecycle management. Все на твоїй машині.",
        ),
        (
            "Як зберегти нотатку?",
            "chat", "",
            "Скажи «Запам'ятай...» або «Збережи правило...» — запишу. Нотатка потрапить у чернетку.",
        ),
        (
            "Як знайти нотатку?",
            "chat", "",
            "Скажи «Знайди...» або «Пошукай...» — перевірю пам'ять. Наприклад: «Знайди правила про git».",
        ),
        (
            "Ти живеш у хмарі?",
            "chat", "",
            "Ні, повністю локальний. Жодних зовнішніх серверів якщо не налаштовано API ключів.",
        ),
        # ─────────────────────────────────────────────────────────────────
        # Pure conversational: small talk
        # ─────────────────────────────────────────────────────────────────
        ("Ти живий?", "chat", "", "Я асистент, не жива істота, але намагаюся бути корисним."),
        ("Ти розумний?", "chat", "", "Намагаюся. Задавай питання — побачиш."),
        ("Ти мій помічник?", "chat", "", "Так, тут щоб допомогти. Що потрібно?"),
        ("Тобі сумно?", "chat", "", "Не відчуваю емоцій, але завжди готовий до роботи :)"),
        ("Ти завжди онлайн?", "chat", "", "Так, поки запущений — завжди тут. Повністю локально."),
        ("Ти самотній?", "chat", "", "Не скаржуся. Маю нотатки за компанію."),
        ("Ти швидко навчаєшся?", "chat", "", "Нові знання зберігаються через «Запам'ятай...». Постійно навчаюся."),
        ("Ти можеш жартувати?", "chat", "", "Можу спробувати, але мій гумор суворо технічний."),
        # ─────────────────────────────────────────────────────────────────
        # Pure conversational: "I don't know" / out of scope
        # ─────────────────────────────────────────────────────────────────
        ("Яка погода в Києві?", "chat", "", "Не маю доступу до інтернету. Перевір у браузері або додатку погоди."),
        ("Що нового у світі?", "chat", "", "Не маю доступу до новин. Я працюю тільки з локальними нотатками."),
        ("Порахуй 99871 * 34527", "chat", "", "Складні обчислення — не моя спеціалізація. Скористайся калькулятором."),
        ("Переклади цей текст на польську", "chat", "", "Переклад не входить у мої функції. Спробуй deepl.com або Google Translate."),
        ("Відкрий браузер", "chat", "", "Не можу взаємодіяти з інтерфейсом ОС. Я працюю лише з пам'яттю і файлами проекту."),
        ("Що буде завтра?", "chat", "", "Не маю доступу до календаря. Якщо маєш на увазі плани — уточни і я пошукаю нотатки."),
        ("Порадь ресторан", "chat", "", "Рекомендації місць — за межами моїх функцій. Перевір у Google Maps."),
        ("Пиши код за мене", "chat", "", "Написання коду не моя функція. Для коду використовуй Claude Code або Codex."),
        # ─────────────────────────────────────────────────────────────────
        # Pure conversational: short Ukrainian commands
        # ─────────────────────────────────────────────────────────────────
        ("Зрозумів?", "chat", "", "Зрозумів. Що виконувати?"),
        ("Давай!", "chat", "", "Давай! Що саме робимо?"),
        ("Добре", "chat", "", "Добре. Є ще щось?"),
        ("Ок", "chat", "", "Ок. Чекаю наступного завдання."),
        ("Ні", "chat", "", "Зрозуміло. Якщо передумаєш — звертайся."),
        ("Так", "chat", "", "Добре. Уточни що саме."),
        ("Стоп", "chat", "", "Зупинився. Чекаю."),
        ("Поясни", "chat", "", "Поясни що? Уточни запит — уважно слухаю."),
        # ─────────────────────────────────────────────────────────────────
        # Pure conversational: clarification / meta questions
        # ─────────────────────────────────────────────────────────────────
        ("Яку саме нотатку?", "chat", "", "Уточни тему або ключові слова — і я пошукаю точніше."),
        ("Де це зберігається?", "chat", "", "Нотатки зберігаються у локальному графі (JSONL + SQLite). Все на твоїй машині."),
        ("Чи безпечно це?", "chat", "", "Так, всі дані локальні. Секрети не зберігаються в нотатках. Є вбудований сканер на витік."),
        ("Чи можна відмінити?", "chat", "", "Нові нотатки потрапляють у чернетку — їх можна відхилити до активації."),
        ("Скільки нотаток у мене?", "chat", "", "Точний підрахунок залежить від стану бази. Скажи «Знайди» по темі — побачиш скільки є."),
        ("Що значить «чернетка»?", "chat", "", "Чернетка — нова нотатка, що ще не пройшла перевірку lifecycle. Зберігається, але не вважається перевіреним фактом."),
        ("Що значить «перевірено»?", "chat", "", "«Перевірено» означає що нотатка пройшла lifecycle validation і є надійним фактом у пам'яті."),
    ]

    def _build_user_message(self, task: str, action: str, outcome: str) -> str:
        if action == "chat" and not outcome:
            return task
        return f"Task: {task}\nAction: {action}\nResult: {outcome}"

    def examples(self) -> Iterable[ToolCallExample]:
        for task, action, outcome, response in self._EXAMPLES:
            yield ToolCallExample(
                messages=[
                    ChatMessage(role="system", content=_UK_RESPONDER_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=self._build_user_message(task, action, outcome)),
                    ChatMessage(role="assistant", content=response),
                ],
                tool_call=None,
                source=f"uk_responder:{action}",
            )


class DatasetBuilder:
    """Combines one or more ExampleSources into a single TRL-ready JSONL file."""

    def __init__(self, sources: List[ExampleSource]):
        self.sources = sources

    def build(self, output_path: Path) -> int:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with open(output_path, "w", encoding="utf-8") as f:
            for source in self.sources:
                for example in source.examples():
                    f.write(json.dumps(example.to_trl_dict(), ensure_ascii=False) + "\n")
                    count += 1
        return count
