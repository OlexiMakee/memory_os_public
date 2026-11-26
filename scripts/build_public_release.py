"""Clean-Room Public Release Exporter & PyPI Wheel Builder for Memory OS.

Copies the package tree into an isolated staging directory, strips all
non-core/personal/out-of-scope modules listed in CLEAN_ROOM_FORBIDDEN_PATHS and
local runtime state, runs the deterministic Clean-Room release gate, and
optionally builds a ready-to-upload PyPI wheel (.whl).

Usage:
    python scripts/build_public_release.py --out /tmp/memory_os_public [--build-wheel]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from memory_os.core.config import MemoryOSConfig
from memory_os.core.release_check import CLEAN_ROOM_FORBIDDEN_PATHS, ReleaseChecker

EXCLUDED_TOP_LEVEL = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
    "dist_public",
    "memory",
    "agent_context",
    "specs",
    "deploy",
    "workflows",
    "launch.sh",
    "ingest_project.py",
    "run_llm_benchmark.py",
    "DEV_STRATEGY.md",
}


def export_clean_room_tree(source_root: Path, staging_dir: Path) -> Dict[str, Any]:
    """Export a clean-room copy of Memory OS and run the public Clean-Room gate."""
    src = Path(source_root).resolve()
    dst = Path(staging_dir).resolve()
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    def _ignore(directory: str, names: List[str]) -> List[str]:
        ignored = []
        rel_dir = Path(directory).resolve().relative_to(src)
        for name in names:
            if name in {"__pycache__", ".DS_Store", ".pytest_cache"} or name.endswith((".pyc", ".egg-info")):
                ignored.append(name)
                continue
            if rel_dir == Path(".") and name in EXCLUDED_TOP_LEVEL:
                ignored.append(name)
                continue
        return ignored

    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore)

    stripped: List[str] = []
    for rel_forbidden in CLEAN_ROOM_FORBIDDEN_PATHS:
        target = dst / rel_forbidden
        if target.is_dir():
            shutil.rmtree(target)
            stripped.append(rel_forbidden)
        elif target.is_file():
            target.unlink()
            stripped.append(rel_forbidden)

    # Create empty clean memory scaffold for gate verification
    (dst / "memory").mkdir(exist_ok=True)
    for fname in ("nodes.jsonl", "edges.jsonl", "events.jsonl"):
        (dst / "memory" / fname).write_text("", encoding="utf-8")
    cfg_path = dst / "memory_os.config.json"
    cfg_path.write_text(
        json.dumps({"memory_dir": "memory", "db_path": "memory/memory_os.db"}, indent=2) + "\n",
        encoding="utf-8",
    )

    cfg = MemoryOSConfig(str(cfg_path))
    checker = ReleaseChecker(cfg)
    clean_room = checker._check_public_clean_room()
    deps = checker._check_core_dependencies()
    private_files = checker._check_public_private_files()

    # Remove temporary config/memory before packaging so wheel stays pure
    shutil.rmtree(dst / "memory")
    cfg_path.unlink()

    checks = [clean_room.to_dict(), deps.to_dict(), private_files.to_dict()]
    ok = all(c["ok"] for c in checks)
    return {
        "ok": ok,
        "staging_dir": str(dst),
        "stripped_paths": stripped,
        "checks": checks,
    }


def build_wheel(staging_dir: Path, wheel_out_dir: Path) -> Dict[str, Any]:
    wheel_out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        str(staging_dir),
        "-w",
        str(wheel_out_dir),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    wheels = sorted(str(p) for p in wheel_out_dir.glob("*.whl"))
    return {
        "ok": res.returncode == 0 and bool(wheels),
        "exit_code": res.returncode,
        "wheels": wheels,
        "stderr": res.stderr.strip()[-500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Clean-Room public Memory OS tree and optionally build wheel.")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]), help="Source Memory OS repo root.")
    parser.add_argument("--out", required=True, help="Target clean-room staging directory.")
    parser.add_argument("--build-wheel", action="store_true", help="Build a .whl package into <out>/dist.")
    parser.add_argument("--format", choices={"text", "json"}, default="text")
    args = parser.parse_args()

    result = export_clean_room_tree(Path(args.source), Path(args.out))
    if result["ok"] and args.build_wheel:
        wheel_res = build_wheel(Path(args.out), Path(args.out) / "dist")
        result["wheel_build"] = wheel_res
        result["ok"] = result["ok"] and wheel_res["ok"]

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Clean-Room Export: {'PASS' if result['ok'] else 'FAIL'} -> {result['staging_dir']}")
        print(f"  stripped ({len(result['stripped_paths'])}): {', '.join(result['stripped_paths']) or '(none)'}")
        for chk in result["checks"]:
            print(f"  [{'OK' if chk['ok'] else 'FAIL'}] {chk['name']}: {chk['detail']}")
        if "wheel_build" in result:
            wb = result["wheel_build"]
            print(f"  wheel: {'OK' if wb['ok'] else 'FAIL'} -> {', '.join(wb['wheels']) or wb['stderr']}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
