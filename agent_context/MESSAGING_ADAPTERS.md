# Messaging Adapters: Telegram and Discord

Status: spec and adapter code done; daemon wiring deferred (needs responder LoRA first).
Date: 2026-06-28.
Audience: repository owner, implementation agents.
Public policy: safe to publish adapter source; do not publish token values or private bot info.

---

## Architecture

```
Telegram / Discord user message
        |
  webhook / polling endpoint    (daemon layer — not yet built)
        |
  TelegramAdapter.parse_update() / DiscordAdapter.parse_event()
        |
  normalized IncomingMessage dict
        |
  ActionBrain.propose_action()           ← classifies: tool_intent vs conversational
        |
       / \
      /   \
 tool     conversational
 intent   intent
   |           |
Executor   Responder          ← responder LoRA (deferred, not yet trained)
   |           |
 result     reply_text
       \   /
   send_message(chat_id, text)
```

Both adapters are in `src/memory_os/adapters/` and follow the standard Layer C optional-adapter
contract: no extra package required (stdlib urllib only), all public methods return
`{"ok": bool, ...}` and never raise.

---

## Adapter Interface

### TelegramAdapter (`src/memory_os/adapters/telegram_adapter.py`)

```python
from memory_os.adapters.telegram_adapter import TelegramAdapter

adapter = TelegramAdapter()           # reads TELEGRAM_BOT_TOKEN from env
adapter = TelegramAdapter(token="...")  # explicit (avoid logging in CI)

# Send a message
result = adapter.send_message(chat_id=123456, text="Hello")
# {"ok": True, "message_id": 789}

# Long-poll for updates (single request, not a loop — loop belongs in daemon)
result = adapter.get_updates(offset=None)
# {"ok": True, "updates": [...raw Telegram update dicts...]}

# Parse an update (pure, no network)
normalized = adapter.parse_update(raw_update)
# {
#   "platform": "telegram",
#   "update_id": int,
#   "message_id": int,
#   "chat_id": int,       ← use this as reply target
#   "user_id": int,
#   "username": str,
#   "text": str,          ← the message to route
#   "raw": dict
# }

# Register a webhook URL
result = adapter.set_webhook("https://your.host/webhook/telegram")

# Remove webhook (switch back to polling mode)
result = adapter.delete_webhook()

# Offline audit
result = adapter.audit()
# {"available": True, "token_configured": True, "bot_api_base": "..."}
```

### DiscordAdapter (`src/memory_os/adapters/discord_adapter.py`)

```python
from memory_os.adapters.discord_adapter import DiscordAdapter

adapter = DiscordAdapter()            # reads DISCORD_BOT_TOKEN from env

# Send a message
result = adapter.send_message(channel_id="123456789", text="Hello")
# {"ok": True, "message_id": "987654321"}

# Send a threaded reply
result = adapter.send_reply(channel_id="...", message_id="...", text="...")

# Get channel info
result = adapter.get_channel(channel_id="...")
# {"ok": True, "id": "...", "name": "general", "type": 0, "guild_id": "..."}

# Parse a Gateway dispatch event (pure, no network)
normalized = adapter.parse_event(raw_event)
# {
#   "platform": "discord",
#   "event_type": "MESSAGE_CREATE",
#   "message_id": str,
#   "channel_id": str,    ← use this as reply target
#   "guild_id": str,
#   "user_id": str,
#   "username": str,
#   "text": str,
#   "is_bot": bool,       ← filter bots: if is_bot, skip
#   "raw": dict
# }

# Offline audit
result = adapter.audit()
# {"available": True, "token_configured": True, "rest_api_base": "..."}
```

---

## Environment Variables

Add to `.env` (gitignored):

```
# Telegram Bot (from https://t.me/BotFather)
TELEGRAM_BOT_TOKEN=<your bot token>

# Discord Bot (from https://discord.com/developers/applications)
DISCORD_BOT_TOKEN=<your bot token>
```

Security: tokens are read from env at instantiation time; never appear in `audit()` output,
logs, or evidence bundles. The adapters do not store anything beyond the current request.

---

## Routing Logic (to implement in daemon layer)

The message routing loop belongs in a daemon or a thin CLI command, not in the adapter.
Sketch of the logic to implement:

```python
from memory_os.adapters.telegram_adapter import TelegramAdapter
from memory_os.agent_brain.orchestrator import Orchestrator
from memory_os.agent_brain.action_brain import LocalLLMActionBrain
from memory_os.agent_brain.executors import MemorySearchExecutor, MemoryWriteExecutor

tg = TelegramAdapter()
brain = LocalLLMActionBrain()
orchestrator = Orchestrator(brain=brain, executors={...})

while True:
    result = tg.get_updates(offset=last_offset)
    for raw in result.get("updates", []):
        msg = tg.parse_update(raw)
        last_offset = (msg["update_id"] or 0) + 1

        if not msg["text"]:
            continue

        # Route: tool intent → execute; conversational → responder (future)
        action = brain.propose_action(msg["text"])
        if action["action"] in ("memory.search", "memory.write", "file.read"):
            exec_result = orchestrator.execute(action)
            reply = format_exec_result(exec_result)
        else:
            # Future: responder LoRA or fallback to cloud LLM
            reply = "Ця функція ще не підключена."

        tg.send_message(msg["chat_id"], reply)
```

For Discord, replace the polling loop with a discord.py `on_message` event handler that calls
`adapter.parse_event(message_to_dict(message))`.

---

## Discord Gateway vs REST

The `DiscordAdapter` implements **REST only** (send messages, get channel info).
Receiving messages from Discord requires the **Gateway** (WebSocket connection with bot intents).
Options:

1. **discord.py library** — `pip install discord.py`; run an async `discord.Client` with
   `intents.message_content = True`. The `DiscordAdapter.parse_event()` can be called on the
   raw dict version of incoming `discord.Message` objects.
2. **Interactions webhook** — only works for slash commands, not regular messages.
3. **discord.py is strongly recommended** for any real Discord bot.

The REST-only adapter is enough for:
- Sending replies and notifications from daemon/scripts.
- Parsing already-received event payloads.
- Offline testing and CI validation.

---

## Responder LoRA (deferred — needed before full chatbot mode)

The current `action_router` adapter (`role=action`) handles tool classification only.
For natural language replies ("conversational intent"), a separate adapter is needed:

```
role = "responder"
base = Qwen3.5-4B-Base (or instruct variant)
dataset = Ukrainian-language conversation examples (Telegram-style)
training_method = "sft"  then optionally "dpo"
```

Steps to build it:
1. Collect 100-200 representative user↔bot conversation pairs in Ukrainian.
2. Build dataset: `memory_os lora dataset build --source responder`.
3. Render training script: `memory_os lora script render --adapter responder`.
4. Train on RTX 3060 Ti in `.venv-train`.
5. Eval: `memory_os eval run agent-responder-quality`.
6. If pass_rate ≥ 0.66: `memory_os lora registry promote --adapter responder`.
7. Convert to GGUF: `convert_lora_to_gguf.py` → `responder_v001.gguf`.
8. Set `LLAMA_CPP_LORA=/home/oleksii/models/gguf/responder_v001.gguf` in `.env`.

Until the responder LoRA exists, the daemon should fall back to a cloud LLM call
(Gemini/OpenRouter) for conversational replies, gated by the user's budget settings.

---

## CLI Audit

Both adapters are included in `memory_os adapters audit`:

```bash
PYTHONPATH=src python -m memory_os adapters audit
# telegram   available=True
# discord    available=True
```

After setting tokens in `.env`:

```bash
PYTHONPATH=src python -m memory_os adapters audit --format json
# "telegram": {"available": true, "token_configured": true, ...}
# "discord":  {"available": true, "token_configured": true, ...}
```

---

## Security Checklist

Before wiring into daemon:

- [ ] `TELEGRAM_BOT_TOKEN` and `DISCORD_BOT_TOKEN` in `.env` (gitignored).
- [ ] Tokens never appear in `evidence/`, context packs, logs, or audit output.
- [ ] `parse_update()` / `parse_event()` treat all incoming text as untrusted user input.
- [ ] Run `memory_os security scan` before persisting any incoming message as a memory node.
- [ ] Rate-limit outbound send_message calls (Telegram: 30 msg/sec per chat limit;
  Discord: 5 msg/sec per channel under normal conditions).
- [ ] Discord: never send to channels where the bot lacks `SEND_MESSAGES` permission;
  check `get_channel()` result and guild permissions before sending.
- [ ] Telegram: filter out updates from unknown senders unless the bot is designed for
  public use; maintain an allowlist in `.env` or config if user-restricted.
- [ ] `is_bot=True` events in Discord must be filtered out to prevent bot loops.
- [ ] Incoming messages must not be forwarded to LLMs with system-prompt injection potential
  without passing through `security_scan.py` or equivalent redaction.

---

## Open Questions (record for future decision)

1. **Polling vs webhook?** Polling is simpler for local dev; webhook requires a public HTTPS
   endpoint (ngrok or a VPS). Defer the choice to daemon implementation.
2. **Multi-user vs single-user?** Current memory graph is single-user. Multi-user Telegram bots
   need per-user memory isolation. Deferred until user namespace design is agreed.
3. **Message persistence?** Incoming Telegram/Discord messages as memory nodes? Could be noisy.
   Only persist when explicitly requested ("remember this") or after explicit confirmation.
4. **Ukrainian keyboard for mobile?** The responder LoRA should be trained on Ukrainian to avoid
   switching languages mid-chat. The action_router can stay English-prompted (user input passes
   through; only the routing decision needs to be in English).
