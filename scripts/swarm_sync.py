#!/usr/bin/env python3
import sys
import argparse
import json
import fcntl
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from contextlib import contextmanager

BACKLOG_FILE = Path("swarm_backlog.json")
LEASES_FILE = Path("data/swarm_leases.json")

@contextmanager
def locked_json_read_write(file_path: Path):
    """Context manager for reading and writing JSON files under an exclusive file lock."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Use "a+" then seek to avoid truncating file before lock is acquired
    with open(file_path, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.seek(0)
            content = f.read().strip()
            data = json.loads(content) if content else []
        except Exception:
            data = []
        
        yield f, data

def paths_conflict(p1: str, p2: str) -> bool:
    """Check if p1 and p2 conflict (either identical, or one is a subdirectory of the other)."""
    try:
        parts1 = Path(p1).resolve().parts
        parts2 = Path(p2).resolve().parts
    except Exception:
        parts1 = Path(p1).parts
        parts2 = Path(p2).parts
    
    min_len = min(len(parts1), len(parts2))
    return parts1[:min_len] == parts2[:min_len]

def get_active_conflicts(requested_files: List[str], backlog: List[Dict[str, Any]], leases: Dict[str, List[str]]) -> List[Tuple[str, str, str]]:
    """Returns a list of conflicts as (task_id, agent, conflicting_file)."""
    running_tasks = {t["id"]: t for t in backlog if t.get("status") in ("running", "pending")}
    conflicts = []
    
    for task_id, files in leases.items():
        if task_id in running_tasks:
            agent = running_tasks[task_id].get("agent", "unknown")
            for req_file in requested_files:
                for locked_file in files:
                    if paths_conflict(req_file, locked_file):
                        conflicts.append((task_id, agent, locked_file))
                        
    return conflicts

def cmd_register(task_id: str, agent: str, files_str: str) -> int:
    requested_files = [f.strip() for f in files_str.split(",") if f.strip()]
    
    with locked_json_read_write(BACKLOG_FILE) as (backlog_f, backlog):
        with locked_json_read_write(LEASES_FILE) as (leases_f, leases_data):
            # leases_data is a dict or list; make sure it's a dict
            if not isinstance(leases_data, dict):
                leases_data = {}
                
            conflicts = get_active_conflicts(requested_files, backlog, leases_data)
            if conflicts:
                print(f"[SwarmSync] ERROR: Edit conflict detected for task '{task_id}'!", file=sys.stderr)
                for cid, cagent, cfile in conflicts:
                    print(f"  - File '{cfile}' is currently locked by task '{cid}' (Agent: {cagent})", file=sys.stderr)
                return 1
            
            # Register task in leases
            leases_data[task_id] = requested_files
            leases_f.seek(0)
            leases_f.truncate()
            json.dump(leases_data, leases_f, indent=2)
            
            # Register/update task in backlog
            task_found = False
            now_str = datetime.now().isoformat()
            for task in backlog:
                if task.get("id") == task_id:
                    task["status"] = "pending"
                    task["agent"] = agent
                    task["files"] = requested_files
                    task["updated_at"] = now_str
                    task_found = True
                    break
            
            if not task_found:
                backlog.append({
                    "id": task_id,
                    "status": "pending",
                    "agent": agent,
                    "files": requested_files,
                    "last_message": "Registered via swarm_sync",
                    "updated_at": now_str
                })
                
            backlog_f.seek(0)
            backlog_f.truncate()
            json.dump(backlog, backlog_f, indent=2)
            
            print(f"[SwarmSync] Task '{task_id}' successfully registered (Agent: {agent}, Locks: {len(requested_files)}).")
            return 0

def cmd_update(task_id: str, status: str, message: str) -> int:
    with locked_json_read_write(BACKLOG_FILE) as (backlog_f, backlog):
        task_found = False
        now_str = datetime.now().isoformat()
        for task in backlog:
            if task.get("id") == task_id:
                task["status"] = status
                task["last_message"] = message
                task["updated_at"] = now_str
                task_found = True
                break
                
        if not task_found:
            backlog.append({
                "id": task_id,
                "status": status,
                "agent": "unknown",
                "files": [],
                "last_message": message,
                "updated_at": now_str
            })
            
        backlog_f.seek(0)
        backlog_f.truncate()
        json.dump(backlog, backlog_f, indent=2)
        
        # If task reached terminal state, release leases
        if status in ("completed", "failed", "cancelled"):
            with locked_json_read_write(LEASES_FILE) as (leases_f, leases_data):
                if isinstance(leases_data, dict) and task_id in leases_data:
                    del leases_data[task_id]
                    leases_f.seek(0)
                    leases_f.truncate()
                    json.dump(leases_data, leases_f, indent=2)
                    
        print(f"[SwarmSync] Task '{task_id}' updated to '{status}'.")
        return 0

def cmd_release(task_id: str) -> int:
    with locked_json_read_write(LEASES_FILE) as (leases_f, leases_data):
        if isinstance(leases_data, dict) and task_id in leases_data:
            del leases_data[task_id]
            leases_f.seek(0)
            leases_f.truncate()
            json.dump(leases_data, leases_f, indent=2)
            print(f"[SwarmSync] Leases for task '{task_id}' released.")
        else:
            print(f"[SwarmSync] No active leases found for task '{task_id}'.")
    return 0

def cmd_status() -> int:
    if not BACKLOG_FILE.exists():
        print("No swarm backlog found (swarm_backlog.json does not exist).")
        return 0
        
    try:
        with open(BACKLOG_FILE, "r") as f:
            backlog = json.load(f)
    except Exception as e:
        print(f"Error reading backlog: {e}", file=sys.stderr)
        return 1
        
    leases = {}
    if LEASES_FILE.exists():
        try:
            with open(LEASES_FILE, "r") as f:
                leases = json.load(f)
        except Exception:
            pass
            
    print("\n=== Swarm Sync Backlog Status ===")
    print(f"| {'Task ID':<20} | {'Status':<13} | {'Agent':<10} | {'Locks':<5} | {'Last Message':<45} |")
    print(f"| {'-'*20} | {'-'*13} | {'-'*10} | {'-'*5} | {'-'*45} |")
    
    for task in backlog:
        tid = task.get("id", "unknown")
        status = task.get("status", "unknown")
        agent = task.get("agent", "unknown")
        locks_count = len(leases.get(tid, task.get("files", [])))
        msg = task.get("last_message", "")
        if len(msg) > 42:
            msg = msg[:42] + "..."
        print(f"| {tid:<20} | {status:<13} | {agent:<10} | {locks_count:<5} | {msg:<45} |")
        
    if leases:
        print("\nActive File Locks:")
        for tid, files in leases.items():
            print(f"  - Task '{tid}':")
            for f in files:
                print(f"    * {f}")
    print()
    return 0

def cmd_clear() -> int:
    with locked_json_read_write(BACKLOG_FILE) as (backlog_f, backlog):
        backlog_f.seek(0)
        backlog_f.truncate()
        json.dump([], backlog_f)
        
    with locked_json_read_write(LEASES_FILE) as (leases_f, leases):
        leases_f.seek(0)
        leases_f.truncate()
        json.dump({}, leases_f)
        
    print("[SwarmSync] Backlog and leases successfully cleared.")
    return 0

def main():
    parser = argparse.ArgumentParser(description="Swarm Sync Orchestration Utility.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # status
    subparsers.add_parser("status", help="Show all tasks and active locks.")
    
    # register
    reg_parser = subparsers.add_parser("register", help="Register a task and request file locks.")
    reg_parser.add_argument("--task_id", required=True)
    reg_parser.add_argument("--agent", required=True)
    reg_parser.add_argument("--files", default="", help="Comma-separated file paths to lock.")
    
    # update
    upd_parser = subparsers.add_parser("update", help="Update task status safely.")
    upd_parser.add_argument("--task_id", required=True)
    upd_parser.add_argument("--status", required=True, choices=["pending", "running", "completed", "failed", "cancelled", "pending_limit"])
    upd_parser.add_argument("--message", default="")
    
    # release
    rel_parser = subparsers.add_parser("release", help="Release locks for a task.")
    rel_parser.add_argument("--task_id", required=True)
    
    # clear
    subparsers.add_parser("clear", help="Clear backlog and leases.")
    
    args = parser.parse_args()
    
    if args.command == "status":
        sys.exit(cmd_status())
    elif args.command == "register":
        sys.exit(cmd_register(args.task_id, args.agent, args.files))
    elif args.command == "update":
        sys.exit(cmd_update(args.task_id, args.status, args.message))
    elif args.command == "release":
        sys.exit(cmd_release(args.task_id))
    elif args.command == "clear":
        sys.exit(cmd_clear())

if __name__ == "__main__":
    main()
