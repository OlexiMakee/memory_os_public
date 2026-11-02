import json
from datetime import timezone
from pathlib import Path
from typing import Any, Dict, List


UTC = timezone.utc
def write_if_missing(path: Path, content: str, actions: List[str]) -> None:
    if path.exists():
        actions.append(f"exists {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    actions.append(f"created {path}")

def append_if_absent(path: Path, marker: str, content: str, actions: List[str]) -> None:
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if marker in text:
            actions.append(f"already integrated {path}")
            return
        path.write_text(text.rstrip() + "\n" + content.lstrip(), encoding="utf-8")
        actions.append(f"updated {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.lstrip(), encoding="utf-8")
    actions.append(f"created {path}")

def _safe_yaml_dump(payload: Dict[str, Any]) -> str:
    try:
        import yaml
    except ModuleNotFoundError:
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return yaml.safe_dump(payload, allow_unicode=True, default_flow_style=False, sort_keys=False)
