#!/usr/bin/env python3
import sys
import os
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "memory"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_os import MemoryOSConfig, MemoryValidator

def log_error(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)

def validate_nodes() -> bool:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    validator = MemoryValidator(config)
    errors = validator.validate_nodes()
    if errors:
        for err in errors:
            log_error(err)
        return False
    return True

def validate_edges() -> bool:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    validator = MemoryValidator(config)
    errors = validator.validate_edges()
    if errors:
        for err in errors:
            log_error(err)
        return False
    return True

def validate_events() -> bool:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    config.data["memory_dir"] = str(MEMORY_DIR)
    validator = MemoryValidator(config)
    errors = validator.validate_events()
    if errors:
        for err in errors:
            log_error(err)
        return False
    return True

def validate_proposals_file(proposals_file: Path) -> List[str]:
    config = MemoryOSConfig()
    config.root_dir = ROOT
    validator = MemoryValidator(config)
    return validator.validate_proposals_file(proposals_file)

def main() -> int:
    config_path = os.environ.get("MEMORY_OS_CONFIG_PATH")
    config = MemoryOSConfig(config_path)
    validator = MemoryValidator(config)

    nodes_errors = validator.validate_nodes()
    edges_errors = validator.validate_edges()
    events_errors = validator.validate_events()
    proposal_errors = validator.validate_proposals_file()

    all_errors = nodes_errors + edges_errors + events_errors + proposal_errors

    if all_errors:
        for err in all_errors:
            log_error(err)
        log_error("Memory OS validation failed.")
        return 1
    
    print("Memory OS validation passed successfully.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
