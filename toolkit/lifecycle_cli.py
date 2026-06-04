#!/usr/bin/env python3
import sys
import os
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "memory"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_os import MemoryOSConfig, LifecycleManager

def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    lm = LifecycleManager(config)
    return lm._load_jsonl(Path(path))

def append_jsonl(path: Path, item: Dict[str, Any]) -> None:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    lm = LifecycleManager(config)
    lm._append_jsonl(Path(path), item)

def write_jsonl(path: Path, items: List[Dict[str, Any]]) -> None:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    lm = LifecycleManager(config)
    lm._write_jsonl(Path(path), items)

def cmd_propose(args: argparse.Namespace) -> int:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    lm = LifecycleManager(config)
    return lm.propose(
        node_id=args.id,
        node_type=args.type,
        summary=args.summary,
        evidence=args.evidence,
        related_nodes=args.related_nodes,
        validator=args.validator
    )

def cmd_transition(args: argparse.Namespace) -> int:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    lm = LifecycleManager(config)
    return lm.transition(validator=args.validator)

def cmd_manifest(args: Optional[argparse.Namespace]) -> int:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    lm = LifecycleManager(config)
    return lm.manifest()

def cmd_prune(args: Optional[argparse.Namespace]) -> int:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    lm = LifecycleManager(config)
    return lm.prune()

def main() -> int:
    parser = argparse.ArgumentParser(description="Memory OS Lifecycle Transition Manager")
    parser.add_argument("--config", help="Path to memory_os.config.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Propose
    p_propose = subparsers.add_parser("propose", help="Propose a new rule or fact memory node.")
    p_propose.add_argument("--id", required=True, help="Namespace ID of node.")
    p_propose.add_argument("--type", choices=["rule", "fact", "variable"], required=True)
    p_propose.add_argument("--summary", required=True, help="Short text summary.")
    p_propose.add_argument("--evidence", required=True, help="Comma-separated evidence file paths.")
    p_propose.add_argument("--related-nodes", help="Comma-separated related node IDs.")
    p_propose.add_argument("--validator", help="Validator context ID.")

    # Transition
    p_trans = subparsers.add_parser("transition", help="Transition draft nodes through trust states.")
    p_trans.add_argument("--validator", help="Validator context ID.")

    # Manifest
    subparsers.add_parser("manifest", help="Compute metrics and SHA256 checksum manifest.")

    # Prune
    subparsers.add_parser("prune", help="Purge stale or superseded memory nodes.")

    args = parser.parse_args()

    global ROOT, MEMORY_DIR
    config_path = args.config or os.environ.get("MEMORY_OS_CONFIG_PATH")
    config = MemoryOSConfig(config_path)
    ROOT = config.root_dir
    MEMORY_DIR = config.memory_dir

    if args.command == "propose":
        return cmd_propose(args)
    elif args.command == "transition":
        return cmd_transition(args)
    elif args.command == "manifest":
        return cmd_manifest(args)
    elif args.command == "prune":
        return cmd_prune(args)

    return 0

if __name__ == "__main__":
    sys.exit(main())
