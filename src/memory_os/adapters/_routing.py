"""Command parsing and update routing for the Telegram polling daemon.

Decides what an incoming Telegram message means (slash command vs plain
text vs leaked swarm protocol text) and where it should go — without
itself performing dispatch or relay I/O.
"""

from __future__ import annotations

import json
import logging

from memory_os.toolkit.agent_registry import KNOWN_AGENTS, load_agent_registry

logger = logging.getLogger(__name__)


class _RoutingMixin:
    def _parse_swarm_command(self, text: str, chat_id) -> dict:
        stripped = text.strip()
        if not stripped:
            return {"action": "help", "args": {}}

        command, _, rest = stripped.partition(" ")
        command = command.split("@")[0].lower()
        rest = rest.strip()

        agent_map = {f"/{a}": a for a in KNOWN_AGENTS}
        agent_map.update({
            "/swarm": "auto",
            "/auto": "auto",
        })

        if command in agent_map:
            agent = agent_map[command]
            if not rest:
                return {"action": "session.set", "args": {"agent": agent}}
            # /swarm and /auto → formal SWARM task protocol; explicit agents → direct delivery
            action = "swarm.dispatch" if command in ("/swarm", "/auto") else "session.dispatch"
            return {"action": action, "args": {"agent": agent, "prompt": rest, "persist_session": True}}


        if command == "/note":
            return {"action": "note.add", "args": {"text": rest}}

        if command == "/task":
            if not rest:
                agents_str = "|".join(KNOWN_AGENTS)
                return {"action": "error", "args": {"message": f"Використання: /task [{agents_str}] <prompt>"}}
            parts = rest.split(maxsplit=1)
            if parts[0] in KNOWN_AGENTS:
                if len(parts) == 1:
                    return {"action": "error", "args": {"message": "Завдання обов'язкове."}}
                return {"action": "swarm.dispatch", "args": {"agent": parts[0], "prompt": parts[1]}}
            return {"action": "swarm.dispatch", "args": {"agent": "auto", "prompt": rest}}

        if command == "/status":
            return {"action": "swarm.status", "args": {"task_id": rest or ""}}
        if command == "/resume":
            return {"action": "swarm.resume", "args": {"limit": int(rest) if rest.isdigit() else 5}}
        if command == "/search":
            if not rest:
                return {"action": "error", "args": {"message": "Використання: /search <query>"}}
            return {"action": "memory.search", "args": {"query": rest}}
        if command in ("/help", "/start"):
            return {"action": "help", "args": {}}

        # Any unknown slash commands / plain text: pass through AS-IS.
        return {"action": "session.dispatch", "args": {"agent": None, "prompt": stripped}}

    def _swarm_help(self) -> str:
        from memory_os.toolkit.agent_health import AgentHealthProbe
        probe = AgentHealthProbe(self._root)
        agents = KNOWN_AGENTS
        lines = ["🐝 **Memory OS Swarm Control**\n", "Доступні агенти рою:"]
        for a in agents:
            h = probe.check(a)  # TTL-cached — /help must not block for 7+ seconds
            st = h.get("status", "unknown")
            icon = "🟢" if st == "ok" else ("🔴" if st in ("quota_exhausted", "rate_limited") else "🟡")
            detail = f" ({h.get('detail')})" if st != "ok" else ""
            lines.append(f"{icon} `/{a}` — {st}{detail}")
        lines.append("\n💡 **Режим сесій (/команди)**:")
        agents_cmds = ", ".join(f"`/{a}`" for a in KNOWN_AGENTS)
        lines.append(f"• Надішліть {agents_cmds} — і всі наступні повідомлення йтимуть цьому агенту!")
        lines.append("• `/note <текст>` — зберегти нотатку в накопичувальний буфер.")
        lines.append("• `/swarm` — для автоматичного підбору агента (Failover).")
        lines.append("• `/search <query>` — пошук у базі знань")
        lines.append("• `/status` — стан активних задач")
        lines.append("• `/resume [N]` — короткий звіт після втрати контексту")
        return "\n".join(lines)

    def _ordered_cli_agents(self) -> list[str]:
        """Return cli_agent IDs from registry in TOML declaration order."""
        registry = load_agent_registry(self._root, fallback_to_main=True)
        agents = registry.get("agent", {})
        if not agents:
            return list(KNOWN_AGENTS)
        return [aid for aid, cfg in agents.items() if cfg.get("kind") == "cli_agent"]

    def _status_text(self, task_id: str) -> str:
        if task_id:
            task = self._task_kernel().get(task_id)
            if not task:
                return f"Task not found: {task_id}"
            done_file = self._root / "agent_context" / "done" / f"{task_id}.json"
            if done_file.exists():
                try:
                    done = json.loads(done_file.read_text(encoding="utf-8"))
                    return f"{task_id}: done by {done.get('sender', '?')}\n{done.get('message', '')}"
                except json.JSONDecodeError:
                    pass
            return f"{task_id}: {task.get('status')} agent={task.get('agent')} goal={task.get('goal', '')[:160]}"
        tasks = self._task_kernel().list_tasks()
        recent = tasks[-5:]
        if not recent:
            return "No tasks."
        return "\n".join(f"{t['id']}: {t.get('status')} agent={t.get('agent')} {t.get('title', '')[:80]}" for t in recent)

    def _resume_text(self, limit: int = 5) -> str:
        from memory_os.toolkit.agent_comm import AgentComm, format_resume_report

        report = AgentComm(self._root, config=self.config).resume_report(limit=max(1, min(limit, 10)))
        return format_resume_report(report)

    def _search_text(self, query: str) -> str:
        from memory_os.modules.search import MemorySearcher

        results = MemorySearcher(self.config).search_memory(query, depth=1)[:5]
        if not results:
            return f"No matches for: {query}"
        lines = [f"Found {len(results)} match(es):"]
        for item in results:
            lines.append(f"- {item.get('id')}: {str(item.get('summary', ''))[:180]}")
        return "\n".join(lines)

    _SWARM_PROTOCOL_MARKERS = (
        "[SWARM COMPLETION REQUIRED]",
        "[Swarm Result]",
        "[SWARM MESSAGE",
        "[END SWARM MESSAGE]",
        "memory_os comm send --kind STATUS_REPORT",
        "[TG_DELIVERY task=",
    )

    def _is_swarm_protocol_message(self, text: str) -> bool:
        """Drop inter-agent protocol text that leaked into the Telegram input stream.

        This breaks the feedback loop where a relayed STATUS_REPORT gets re-dispatched
        as a new user task, causing every agent reply to spawn more tasks.
        """
        return any(marker in text for marker in self._SWARM_PROTOCOL_MARKERS)

    def _process_swarm_update(self, text: str, chat_id) -> None:
        if self._is_swarm_protocol_message(text):
            logger.warning(f"[telegram] chat={chat_id} dropped swarm protocol message (relay loop guard)")
            return
        if not self._chat_authorized(chat_id):
            self._send_text(chat_id, "Unauthorized chat. Configure TELEGRAM_ALLOWED_CHAT_IDS in this project .env.")
            return
        command = self._parse_swarm_command(text, chat_id)
        action = command["action"]
        args = command.get("args", {})
        if action == "help":
            self._send_text(chat_id, self._swarm_help())
        elif action == "error":
            self._send_text(chat_id, args.get("message", "Invalid command."))
        elif action == "session.set":
            agent = args["agent"]
            self._session_agent[chat_id] = agent
            self._save_session_state()
            if agent == "auto":
                self._send_text(chat_id, "🎯 Режим переключено на /swarm (автоматичний підбір агентів з рою).")
            else:
                self._send_text(chat_id, f"🎯 Режим переключено на /{agent}. Усі наступні повідомлення надходитимуть йому.")
        elif action == "note.add":
            note_text = args.get("text", "").strip()
            if not note_text:
                self._send_text(chat_id, "📝 Будь ласка, вкажіть текст нотатки після команди. Наприклад: `/note замовити сервер`")
                return
            if chat_id not in self._chat_notes:
                self._chat_notes[chat_id] = []
            self._chat_notes[chat_id].append(note_text)
            count = len(self._chat_notes[chat_id])
            self._send_text(chat_id, f"📝 Нотатку додано! (Всього в накопичувальному буфері: {count}).\nНадішліть завдання або викличте /агента для їх аналізу.")
        elif action == "session.dispatch":
            # Direct delivery — no SWARM task wrapper, no kernel task creation
            explicit_agent = args.get("agent")
            target_agent = explicit_agent or self._session_agent.get(chat_id, "auto")
            if not explicit_agent and target_agent == "auto":
                target_agent = self._last_active_agent.get(chat_id, "auto")
            if args.get("persist_session") and args.get("agent"):
                self._session_agent[chat_id] = args["agent"]
                self._save_session_state()
            prompt = args["prompt"]

            notes = self._chat_notes.get(chat_id, [])
            if notes:
                notes_block = "\n".join(f"• {n}" for n in notes)
                prompt = f"[НАКОПИЧЕНІ НОТАТКИ /NOTE]:\n{notes_block}\n\n[ЗАВДАННЯ / ЗАПИТАННЯ]:\n{prompt}"
                self._chat_notes[chat_id] = []

            dispatch_agent = None if target_agent == "auto" else target_agent
            self._dispatch(chat_id, prompt, agent=dispatch_agent, direct=True)
        elif action == "swarm.dispatch":
            # Formal SWARM task protocol — kernel + AgentComm.send(TASK_ASSIGN)
            explicit_agent = args.get("agent")
            target_agent = explicit_agent or self._session_agent.get(chat_id, "auto")
            if not explicit_agent and target_agent == "auto":
                target_agent = self._last_active_agent.get(chat_id, "auto")
            if args.get("persist_session") and args.get("agent"):
                self._session_agent[chat_id] = args["agent"]
                self._save_session_state()
            prompt = args["prompt"]

            notes = self._chat_notes.get(chat_id, [])
            if notes:
                notes_block = "\n".join(f"• {n}" for n in notes)
                prompt = f"[НАКОПИЧЕНІ НОТАТКИ /NOTE]:\n{notes_block}\n\n[ЗАВДАННЯ / ЗАПИТАННЯ]:\n{prompt}"
                self._chat_notes[chat_id] = []

            dispatch_agent = None if target_agent == "auto" else target_agent
            self._dispatch(chat_id, prompt, agent=dispatch_agent, direct=False)
        elif action == "swarm.status":
            self._send_text(chat_id, self._status_text(args.get("task_id", "")))
        elif action == "swarm.resume":
            self._send_text(chat_id, self._resume_text(args.get("limit", 5)))
        elif action == "memory.search":
            self._send_text(chat_id, self._search_text(args["query"]))

    def process_update(self, raw_update: dict) -> None:
        parsed = self.telegram.parse_update(raw_update)
        text = (parsed.get("text") or "").strip()
        chat_id = parsed.get("chat_id")
        username = parsed.get("username") or str(parsed.get("user_id", "unknown"))
        if not text or not chat_id:
            return

        logger.info(f"[telegram] chat={chat_id} user={username} text={text[:80]!r}")
        if self.swarm_control:
            self._process_swarm_update(text, chat_id)
            return

        task_id = self._create_message_task(username, text)
        result = self._run_message_action(text)
        response = self._render_message_response(text, result)
        send_ok = self._send_message_response(chat_id, response)
        self._finish_message_task(task_id, result, send_ok)
        self._record_conversation(parsed, text, username, task_id, result, response, send_ok)

    def _create_message_task(self, username: str, text: str) -> str | None:
        if not self.track_tasks:
            return None
        try:
            kernel = self._task_kernel()
            task = kernel.create(
                title=f"tg:{username}: {text[:60]}",
                goal=text,
                risk="low",
                capabilities=["action_routing", "respond"],
            )
            task_id = task["id"]
            kernel.claim(task_id, agent="telegram-daemon", lease_minutes=5)
            kernel.start(task_id)
            logger.debug(f"[telegram] task={task_id} created for message")
            return task_id
        except Exception as exc:
            logger.warning(f"[telegram] task tracking failed (non-fatal): {exc}")
            return None

    def _run_message_action(self, text: str):
        try:
            return self.orchestrator.run(text)
        except Exception as exc:
            from memory_os.agent_brain.types import ActionResult
            logger.error(f"[telegram] orchestrator error: {exc}")
            return ActionResult(action="chat", ok=False, data=None, error=str(exc))

    def _render_message_response(self, text: str, result) -> str:
        try:
            return self.responder.respond(text, result)
        except Exception as exc:
            logger.error(f"[telegram] responder error: {exc}")
            return "Вибачте, сталася помилка."

    def _send_message_response(self, chat_id, response: str) -> bool:
        try:
            self._rate_limit(chat_id)
            send_result = self.telegram.send_message(chat_id, response)
            ok = send_result.get("ok", False)
            logger.info(f"[telegram] sent {len(response)} chars to chat={chat_id} ok={ok}")
            return ok
        except Exception as exc:
            logger.error(f"[telegram] send_message failed: {exc}")
            return False

    def _finish_message_task(self, task_id: str | None, result, send_ok: bool) -> None:
        if not task_id or not self.track_tasks:
            return
        try:
            kernel = self._task_kernel()
            summary = f"action={result.action} ok={result.ok} sent={send_ok}"
            if result.ok and send_ok:
                kernel.done(task_id, summary=summary)
            else:
                reason = result.error or ("send failed" if not send_ok else "unknown")
                kernel.block(task_id, reason=reason[:120])
        except Exception as exc:
            logger.warning(f"[telegram] task update failed (non-fatal): {exc}")

    def _record_conversation(
        self, parsed: dict, text: str, username: str, task_id: str | None,
        result, response: str, send_ok: bool,
    ) -> None:
        try:
            log_dir = self._root / "agent_context"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "telegram_conversations.jsonl"

            from datetime import datetime, timezone
            rec = {
                "schema_version": 1,
                "source": "telegram",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "chat_ref": self._subject_ref("chat", parsed.get("chat_id")),
                "user_ref": self._subject_ref("user", parsed.get("user_id") or username),
                "update_id": parsed.get("update_id"),
                "message_id": parsed.get("message_id"),
                "task_id": task_id,
                "user_text": text,
                "action": result.action,
                "action_args": result.action_args,
                "action_ok": result.ok,
                "action_error": result.error,
                "action_data": result.data,
                "response": response,
                "send_ok": send_ok,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning(f"[telegram] conversation logging failed: {exc}")
