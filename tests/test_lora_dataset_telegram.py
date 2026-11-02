import json

from memory_os.core.config import MemoryOSConfig
from memory_os.lora.dataset import DatasetBuilder, TelegramToolCallSource


def test_telegram_tool_call_source_builds_action_router_examples(tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    log_dir = tmp_path / "agent_context"
    log_dir.mkdir()
    log_file = log_dir / "telegram_conversations.jsonl"
    records = [
        {
            "schema_version": 1,
            "source": "telegram",
            "update_id": 10,
            "message_id": 1,
            "user_text": "Знайди нотатки про Ollama",
            "action": "memory.search",
            "action_args": {"query": "Ollama exact logged query"},
            "action_ok": True,
        },
        {
            "schema_version": 1,
            "source": "telegram",
            "update_id": 11,
            "message_id": 2,
            "user_text": "Запам'ятай правило: ніколи не force-push до main",
            "action": "memory.write",
            "action_args": {"summary": "never force-push to main", "type": "rule"},
            "action_ok": True,
        },
        {
            "schema_version": 1,
            "source": "telegram",
            "update_id": 12,
            "message_id": 3,
            "user_text": "Покажи src/memory_os/core/config.py",
            "action": "file.read",
            "action_args": {"path": "README.md"},
            "action_ok": True,
        },
        {
            "schema_version": 1,
            "source": "telegram",
            "update_id": 13,
            "message_id": 4,
            "user_text": "Привіт",
            "action": "chat",
            "action_ok": True,
        },
    ]
    log_file.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n{bad json\n",
        encoding="utf-8",
    )

    config = MemoryOSConfig(config_path=str(cfg_path))
    examples = list(TelegramToolCallSource(config).examples())

    assert len(examples) == 3
    rows = [example.to_trl_dict() for example in examples]
    completions = [json.loads(row["messages"][1]["content"]) for row in rows]
    assert completions[0] == {
        "action": "memory.search",
        "args": {"query": "Ollama exact logged query"},
    }
    assert completions[1] == {
        "action": "memory.write",
        "args": {"summary": "never force-push to main", "type": "rule"},
    }
    assert completions[2] == {
        "action": "file.read",
        "args": {"path": "README.md"},
    }
    assert "<available_actions>" in rows[0]["messages"][0]["content"]
    assert examples[0].source == "telegram:10:1"


def test_telegram_tool_call_source_skips_file_read_without_path(tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    log_dir = tmp_path / "agent_context"
    log_dir.mkdir()
    (log_dir / "telegram_conversations.jsonl").write_text(
        json.dumps({"user_text": "Покажи файл", "action": "file.read"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    config = MemoryOSConfig(config_path=str(cfg_path))

    assert list(TelegramToolCallSource(config).examples()) == []


def test_telegram_tool_call_source_uses_logged_file_read_args_without_path_in_text(tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    log_dir = tmp_path / "agent_context"
    log_dir.mkdir()
    (log_dir / "telegram_conversations.jsonl").write_text(
        json.dumps(
            {
                "user_text": "Покажи головний README",
                "action": "file.read",
                "action_args": {"path": "README.md"},
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )

    config = MemoryOSConfig(config_path=str(cfg_path))
    rows = [example.to_trl_dict() for example in TelegramToolCallSource(config).examples()]

    assert len(rows) == 1
    assert json.loads(rows[0]["messages"][1]["content"]) == {
        "action": "file.read",
        "args": {"path": "README.md"},
    }


def test_dataset_builder_writes_telegram_source_rows(tmp_path):
    cfg_path = tmp_path / "memory_os.config.json"
    cfg_path.write_text(json.dumps({"version": "0.1"}), encoding="utf-8")
    log_dir = tmp_path / "agent_context"
    log_dir.mkdir()
    (log_dir / "telegram_conversations.jsonl").write_text(
        json.dumps({"user_text": "Знайди daemon IPC", "action": "memory.search"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    config = MemoryOSConfig(config_path=str(cfg_path))
    out = tmp_path / "data" / "lora" / "telegram.jsonl"

    count = DatasetBuilder([TelegramToolCallSource(config)]).build(out)

    assert count == 1
    row = json.loads(out.read_text(encoding="utf-8"))
    assert json.loads(row["messages"][1]["content"])["action"] == "memory.search"
