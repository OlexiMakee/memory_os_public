#!/usr/bin/env python3
"""
Memory OS Local Agent — interactive lightweight agent chat runner using local Ollama.
"""

import sys
import os
import json
import argparse
import subprocess
import shlex
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone

try:
    import ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    _OLLAMA_AVAILABLE = False

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import confine_to_root

# Default local model tag
DEFAULT_MODEL = "qwen3:4b"

def _root_dir() -> Path:
    return MemoryOSConfig().root_dir

def load_env_file():
    env_path = _root_dir() / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

# Load environment variables on startup
load_env_file()

def _prompt_text_for_routing(prompt: str) -> str:
    lines = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "]" in stripped:
            suffix = stripped.split("]", 1)[1].strip()
            if not suffix:
                continue
            stripped = suffix
        parts = []
        skip_next = False
        for token in stripped.split():
            if skip_next:
                skip_next = False
                continue
            if token == "--task-id":
                skip_next = True
                continue
            if token.startswith("task_"):
                continue
            parts.append(token)
        if parts:
            lines.append(" ".join(parts))
    return "\n".join(lines)

def get_ollama_client(prompt: str) -> tuple[Any, str]:
    task_lower = _prompt_text_for_routing(prompt).lower()
    complex_keywords = ["fix", "refactor", "bug", "implement", "create", "test", "run pytest", "develop"]
    is_complex = any(k in task_lower for k in complex_keywords)
    
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    cloud_host = os.environ.get("OLLAMA_CLOUD_HOST", "https://api.ollama.com")
    
    if is_complex and api_key:
        model = os.environ.get("OLLAMA_CLOUD_MODEL", "qwen2.5-coder:7b")
        client = ollama.Client(host=cloud_host, headers={"Authorization": f"Bearer {api_key}"})
        return client, model
    else:
        local_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        model = os.environ.get("OLLAMA_LOCAL_MODEL", DEFAULT_MODEL)
        client = ollama.Client(host=local_host)
        return client, model

def _local_ollama_client_and_model() -> tuple[Any, str]:
    local_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    local_model = os.environ.get("OLLAMA_LOCAL_MODEL", DEFAULT_MODEL)
    return ollama.Client(host=local_host), local_model

def _chat_with_local_fallback(
    client: Any,
    resolved_model: str,
    messages: List[Dict[str, Any]],
) -> tuple[Dict[str, Any] | None, Any, str, str | None]:
    try:
        response = client.chat(
            model=resolved_model,
            messages=messages,
            tools=TOOLS_SCHEMA
        )
        return response, client, resolved_model, None
    except Exception as e:
        local_client, local_model = _local_ollama_client_and_model()
        if resolved_model == local_model:
            return None, client, resolved_model, f"Error calling Ollama model '{resolved_model}': {e}"
        fallback_msg = f"Model '{resolved_model}' call failed: {e}. Falling back to local model '{local_model}'."
        print(fallback_msg, file=sys.stderr)
        log_event("llm_call_warning", {"warning": fallback_msg})
        try:
            response = local_client.chat(
                model=local_model,
                messages=messages,
                tools=TOOLS_SCHEMA
            )
            return response, local_client, local_model, None
        except Exception as local_e:
            return None, local_client, local_model, f"Error calling local model fallback '{local_model}': {local_e}"

# execute_command is documented (prompts/local.md) as narrow verification use
# only ("running pytest", single read-only checks) -- a small 4B model's own
# judgment is not a security boundary, so this is an allowlist of exact
# command prefixes, not a denylist of bad ones. shell=False + shlex.split
# means no shell metacharacter (;, &&, |, $(), backticks, redirects) can ever
# reach a shell interpreter, so allowlist bypass via chaining is not possible.
_ALLOWED_COMMAND_PREFIXES = (
    ["pytest"],
    ["python", "-m", "pytest"],
    ["python3", "-m", "pytest"],
    ["git", "status"],
    ["git", "diff"],
    ["git", "log"],
    ["git", "show"],
)

# Define tools schema
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search the Memory OS graph for nodes and facts matching the query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search term or query."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory",
            "description": "Write a new fact, setting, decision, or observation to the Memory OS graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Concise summary of the fact/decision to write."},
                    "type": {
                        "type": "string", 
                        "description": "Type of node, defaults to 'fact'.", 
                        "enum": ["fact", "decision", "setting", "observation"]
                    }
                },
                "required": ["summary"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a local file in the workspace repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Run a shell/bash command and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run."}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_swarm_message",
            "description": "Send a task assignment or status report to another agent in the swarm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Recipient agent name (e.g. claude, agy, codex)."},
                    "kind": {
                        "type": "string", 
                        "description": "Message kind.", 
                        "enum": ["TASK_ASSIGN", "STATUS_REPORT"]
                    },
                    "task_id": {"type": "string", "description": "Unique task ID."},
                    "message": {"type": "string", "description": "Message payload / status report description."}
                },
                "required": ["recipient", "kind", "task_id", "message"]
            }
        }
    }
]

def log_event(event_type: str, data: Dict[str, Any]):
    try:
        default_log_dir = str(_root_dir() / "agent_context" / "agents" / "logs")
        log_dir_str = os.environ.get("MEMORY_OS_LOG_DIR", default_log_dir)
        log_dir = Path(log_dir_str)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "local.log"
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "data": data
        }
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[Logging Error] {e}", file=sys.stderr)

def run_search_memory(query: str) -> str:
    log_event("tool_search_memory_start", {"query": query})
    try:
        from memory_os.modules.search import MemorySearcher
        from memory_os.core.config import MemoryOSConfig
        searcher = MemorySearcher(MemoryOSConfig())
        matches = searcher.search_memory(query, depth=1)
        if not matches:
            res = "No matches found in Memory OS."
        else:
            lines = []
            for m in matches[:10]:
                lines.append(f"[{m.get('id')}] ({m.get('type')}) - {m.get('summary')}")
            res = "\n".join(lines)
        log_event("tool_search_memory_end", {"query": query, "result_summary": res[:120]})
        return res
    except Exception as e:
        err = f"Error searching memory: {e}"
        log_event("tool_search_memory_end", {"query": query, "error": err})
        return err

def run_write_memory(summary: str, node_type: str = "fact") -> str:
    log_event("tool_write_memory_start", {"summary": summary, "type": node_type})
    try:
        cmd = [sys.executable, "-m", "memory_os", "memory", "write", "--type", node_type, summary]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            out = res.stdout.strip() or "Successfully wrote memory."
            log_event("tool_write_memory_end", {"summary": summary, "type": node_type, "result": out})
            return out
        else:
            err = f"Failed to write memory: {res.stderr.strip()}"
            log_event("tool_write_memory_end", {"summary": summary, "type": node_type, "error": err})
            return err
    except Exception as e:
        err = f"Error writing memory: {e}"
        log_event("tool_write_memory_end", {"summary": summary, "type": node_type, "error": err})
        return err

def run_read_file(path: str) -> str:
    log_event("tool_read_file_start", {"path": path})
    try:
        try:
            target_path = confine_to_root(path, _root_dir())
        except ValueError:
            target_path = None
        if target_path is None:
            res = "Error: Access denied (path traversal blocked)."
        elif not target_path.exists():
            res = f"Error: File '{path}' does not exist."
        elif target_path.is_dir():
            res = f"Error: '{path}' is a directory."
        else:
            content = target_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            if len(lines) > 200:
                res = "\n".join(lines[:200]) + "\n... [TRUNCATED]"
            else:
                res = content
        log_event("tool_read_file_end", {"path": path, "result_summary": res[:120]})
        return res
    except Exception as e:
        err = f"Error reading file: {e}"
        log_event("tool_read_file_end", {"path": path, "error": err})
        return err

def run_execute_command(cmd: str) -> str:
    log_event("tool_execute_command_start", {"command": cmd})
    try:
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            res = f"Error: could not parse command: {e}"
            log_event("tool_execute_command_end", {"command": cmd, "error": res})
            return res

        if not any(parts[: len(prefix)] == prefix for prefix in _ALLOWED_COMMAND_PREFIXES):
            res = (
                "Error: command not allowed. Only pytest and read-only git "
                "inspection commands (status/diff/log/show) may run here."
            )
            log_event("tool_execute_command_end", {"command": cmd, "error": res})
            return res

        print(f"\n[Local Executing] {cmd}")
        res_proc = subprocess.run(
            parts, shell=False, cwd=str(_root_dir()), capture_output=True, text=True, timeout=30
        )
        out = []
        if res_proc.stdout:
            out.append(res_proc.stdout)
        if res_proc.stderr:
            out.append(f"--- STDERR ---\n{res_proc.stderr}")
        output_str = "\n".join(out)
        if not output_str.strip():
            res = f"Command finished with exit code {res_proc.returncode} (no output)."
        else:
            res = output_str
        log_event("tool_execute_command_end", {"command": cmd, "exit_code": res_proc.returncode, "result_summary": res[:120]})
        return res
    except subprocess.TimeoutExpired:
        err = "Error: Command timed out after 30 seconds."
        log_event("tool_execute_command_end", {"command": cmd, "error": err})
        return err
    except Exception as e:
        err = f"Error executing command: {e}"
        log_event("tool_execute_command_end", {"command": cmd, "error": err})
        return err

def run_send_swarm_message(recipient: str, kind: str, task_id: str, message: str) -> str:
    log_event("tool_send_swarm_message_start", {"recipient": recipient, "kind": kind, "task_id": task_id, "message": message})
    try:
        cmd = [
            sys.executable, "-m", "memory_os", "comm", "send",
            "--kind", kind,
            "--sender", "local",
            "--task-id", task_id,
            recipient,
            message
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            out = "Successfully sent swarm message."
            log_event("tool_send_swarm_message_end", {"recipient": recipient, "result": out})
            return out
        else:
            err = f"Failed to send swarm message: {res.stderr.strip()}"
            log_event("tool_send_swarm_message_end", {"recipient": recipient, "error": err})
            return err
    except Exception as e:
        err = f"Error sending swarm message: {e}"
        log_event("tool_send_swarm_message_end", {"recipient": recipient, "error": err})
        return err

def load_system_prompt() -> str:
    prompt_file = _root_dir() / "agent_context" / "agents" / "prompts" / "local.md"
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8")
    return "You are Local, a helpful local agent."

def parse_swarm_task(text: str, default_sender: str = "claude"):
    if not text.strip().startswith("[TASK"):
        return None, text, default_sender
    lines = text.splitlines()
    task_id = lines[0].split()[1].replace("]", "").strip()

    sender = default_sender
    prompt_lines = []
    for line in lines[1:]:
        if "[SWARM COMPLETION PROTOCOL]" in line:
            break
        # Extract sender from protocol header if present.
        if line.strip().startswith("sender="):
            parsed = line.strip().removeprefix("sender=").strip()
            if parsed:
                sender = parsed
            continue
        if "[TASK" in line or "[EFFORT" in line:
            continue
        prompt_lines.append(line)
    return task_id, "\n".join(prompt_lines).strip(), sender

def execute_agent_turn(prompt: str, messages: List[Dict[str, Any]], model_name: str) -> str:
    log_event("agent_turn_start", {"prompt": prompt})
    client, resolved_model = get_ollama_client(prompt)
    messages.append({"role": "user", "content": prompt})
    
    for step in range(5):
        log_event("llm_call_start", {"step": step, "message_count": len(messages), "model": resolved_model})
        response, client, resolved_model, err_msg = _chat_with_local_fallback(client, resolved_model, messages)
        if err_msg:
            print(err_msg, file=sys.stderr)
            log_event("llm_call_error", {"error": err_msg})
            return err_msg
            
        assistant_msg = response.get("message", {})
        messages.append(assistant_msg)
        log_event("llm_call_success", {"response_content": assistant_msg.get("content", ""), "tool_calls_proposed": assistant_msg.get("tool_calls", [])})
        
        tool_calls = assistant_msg.get("tool_calls", [])
        if not tool_calls:
            content = assistant_msg.get("content", "")
            if content:
                print(content)
            log_event("agent_turn_end", {"result": content})
            return content
            
        # Execute tool calls
        for tool_call in tool_calls:
            name = tool_call["function"]["name"]
            args = tool_call["function"]["arguments"]
            
            print(f"\n[Local Agent] calling {name}({args})...")
            if name == "search_memory":
                result = run_search_memory(args.get("query", ""))
            elif name == "write_memory":
                result = run_write_memory(args.get("summary", ""), args.get("type", "fact"))
            elif name == "read_file":
                result = run_read_file(args.get("path", ""))
            elif name == "execute_command":
                result = run_execute_command(args.get("command", ""))
            elif name == "send_swarm_message":
                result = run_send_swarm_message(
                    args.get("recipient", ""),
                    args.get("kind", ""),
                    args.get("task_id", ""),
                    args.get("message", "")
                )
            else:
                result = f"Error: Unknown tool '{name}'"
                
            print(f"[Local Agent] result:\n{result}\n")
            
            messages.append({
                "role": "tool",
                "content": result,
                "name": name
            })
            
    print("Local Agent: Max execution steps reached.")
    log_event("agent_turn_end", {"error": "Max steps exceeded."})
    return "Max steps exceeded."

def read_multiline_swarm_message() -> str:
    line = sys.stdin.readline()
    if not line:
        return ""
    if line.strip().startswith("[TASK"):
        lines = [line]
        while True:
            next_line = sys.stdin.readline()
            if not next_line:
                break
            lines.append(next_line)
            if "[END PROTOCOL]" in next_line:
                break
        return "".join(lines)
    return line.strip()

def send_status_report(task_id: str, recipient: str, message: str):
    run_send_swarm_message(recipient, "STATUS_REPORT", task_id, message)

def _run_turn(user_input: str, messages: list, model: str, agent_id: str) -> None:
    """Execute one chat/task turn (swarm-task detection + report, or plain chat)."""
    task_id, actual_prompt, sender = parse_swarm_task(user_input, default_sender=agent_id)
    if task_id:
        print(f"\n[Local Agent] Received Swarm Task: {task_id}")
        print(f"[Local Agent] Prompt: {actual_prompt}\n")

        result = execute_agent_turn(actual_prompt, messages, model)

        summary = f"Local completed task {task_id}. Result: {result[:120]}..."
        send_status_report(task_id, sender, summary)
        print(f"\n[Local Agent] Status Report sent to {sender} for task {task_id}.\n")
    else:
        execute_agent_turn(user_input, messages, model)
        print()

def main():
    if not _OLLAMA_AVAILABLE:
        print("Error: 'ollama' library is required to run the local agent.", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Memory OS Local Agent CLI")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model tag to use.")
    parser.add_argument(
        "-p", "--prompt", default=None,
        help="Run once with this prompt (swarm-task or plain) and exit, instead of the "
             "interactive REPL. Required for non-interactive dispatch (DispatcherEngine).",
    )
    parser.add_argument("--agent-id", default="claude", help="Agent ID to use as fallback sender.")
    args = parser.parse_args()

    # Verify Ollama is running
    try:
        ollama.list()
    except Exception as e:
        print(f"Error: Ollama server is not running or unreachable: {e}", file=sys.stderr)
        sys.exit(1)

    system_prompt = load_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]

    if args.prompt is not None:
        log_event("session_start", {"model": args.model, "mode": "one_shot"})
        try:
            _run_turn(args.prompt, messages, args.model, args.agent_id)
        except Exception as e:
            print(f"\nError in one-shot turn: {e}\n", file=sys.stderr)
            log_event("session_error", {"error": str(e)})
            sys.exit(1)
        log_event("session_end", {"reason": "one_shot_complete"})
        return

    print("=== Memory OS Local Agent ===")
    print(f"Model: {args.model}")
    print("Type '/clear' to reset chat memory, or 'exit'/'quit' to leave.")
    print("============================")

    log_event("session_start", {"model": args.model})

    while True:
        try:
            sys.stdout.write("local> ")
            sys.stdout.flush()

            user_input = read_multiline_swarm_message()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                log_event("session_end", {"reason": "user_exit"})
                break

            if user_input.strip() == "/clear":
                messages = [{"role": "system", "content": system_prompt}]
                print("Chat history cleared.")
                log_event("session_clear", {})
                continue

            _run_turn(user_input, messages, args.model, args.agent_id)

        except KeyboardInterrupt:
            print("\nGoodbye!")
            log_event("session_end", {"reason": "keyboard_interrupt"})
            break
        except Exception as e:
            print(f"\nError in chat loop: {e}\n")
            log_event("session_error", {"error": str(e)})

if __name__ == "__main__":
    main()
