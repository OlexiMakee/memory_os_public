import json
from typing import Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.safe_id import validate_safe_id
from memory_os.lora.types import SkillAdapterSpec


class AdapterRegistry:
    """
    Tracks which LoRA skill adapters exist for this project, *and* every
    version trained for each one: what it's for, which base model/dataset
    it came from, where its rendered training script lives, and whether
    it's a candidate, promoted, retired, or rejected.

    Pure bookkeeping — it never trains anything itself, and it never
    promotes a version on its own. `register()` always lands as a new
    "candidate" version; only an explicit `promote()` call (made after an
    eval run says the candidate is actually better — see
    EvalRunner/`memory_os eval compare`) makes it the one `get()`/`list()`
    report by default. This is the stop-gate: new data -> candidate LoRA
    -> eval -> promote or reject, never new data -> auto-replace.
    """

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.path = config.root_dir / "data" / "lora_adapters.json"

    def _load(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: Dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def register(self, spec: SkillAdapterSpec, script_path: str = "") -> str:
        """Register a new candidate version of `spec.name`. Returns the new
        version id (e.g. 'v003'). Does not touch current_version — call
        promote() once eval confirms it's an improvement."""
        validate_safe_id(spec.name, "adapter name")
        data = self._load()
        entry = data.setdefault(spec.name, {"current_version": None, "versions": {}})
        version_id = f"v{len(entry['versions']) + 1:03d}"
        entry["versions"][version_id] = {
            "status": "candidate",
            "description": spec.description,
            "base_model": spec.base_model,
            "dataset_path": spec.dataset_path,
            "script_path": script_path,
            "target_modules": spec.target_modules,
            "rank": spec.rank,
            "alpha": spec.alpha,
            "notes": spec.notes,
            "role": spec.role,
            "adapter_kind": spec.adapter_kind,
            "training_method": spec.training_method,
            "capabilities": spec.capabilities,
            "compatible_with": spec.compatible_with,
            "incompatible_with": spec.incompatible_with,
            "metrics": {},
        }
        self._save(data)
        return version_id

    def record_metrics(self, name: str, version: str, metrics: Dict[str, float]) -> None:
        """Attach post-eval metrics (accuracy, json_validity, latency_ms, ...)
        to a specific version — the measurable basis a promote()/reject()
        call should be made on. Merges into any metrics already recorded
        rather than replacing them, so separate eval runs (e.g. one suite
        for JSON validity, another for latency) can each contribute."""
        data = self._load()
        entry = data.get(name)
        if entry is None or version not in entry.get("versions", {}):
            raise KeyError(f"unknown adapter/version: {name}/{version}")
        entry["versions"][version].setdefault("metrics", {}).update(metrics)
        self._save(data)

    def promote(self, name: str, version: str) -> None:
        """Make `version` the current one for `name`. Any previously
        promoted version for the same adapter becomes 'retired' rather than
        deleted — the history stays inspectable."""
        data = self._load()
        entry = data.get(name)
        if entry is None or version not in entry.get("versions", {}):
            raise KeyError(f"unknown adapter/version: {name}/{version}")
        for vid, meta in entry["versions"].items():
            if vid != version and meta.get("status") == "promoted":
                meta["status"] = "retired"
        entry["versions"][version]["status"] = "promoted"
        entry["current_version"] = version
        self._save(data)

    def reject(self, name: str, version: str) -> None:
        """Mark a candidate as rejected (eval said it's worse). Does not
        touch current_version — the previously promoted version, if any,
        keeps serving."""
        data = self._load()
        entry = data.get(name)
        if entry is None or version not in entry.get("versions", {}):
            raise KeyError(f"unknown adapter/version: {name}/{version}")
        entry["versions"][version]["status"] = "rejected"
        self._save(data)

    def list(self) -> List[Dict]:
        """One row per adapter: its promoted version if it has one, else
        its newest candidate. Use list_versions() for full history."""
        rows = []
        for name, entry in sorted(self._load().items()):
            versions = entry.get("versions", {})
            if not versions:
                continue
            version_id = entry.get("current_version") or sorted(versions)[-1]
            rows.append({"name": name, "version": version_id, **versions[version_id]})
        return rows

    def list_versions(self, name: str) -> List[Dict]:
        entry = self._load().get(name, {})
        return [{"version": vid, **meta} for vid, meta in sorted(entry.get("versions", {}).items())]

    def get(self, name: str, version: Optional[str] = None) -> Optional[Dict]:
        entry = self._load().get(name)
        if entry is None:
            return None
        versions = entry.get("versions", {})
        vid = version or entry.get("current_version") or (sorted(versions)[-1] if versions else None)
        if vid is None or vid not in versions:
            return None
        return {"version": vid, **versions[vid]}

    def for_role(self, role: str) -> List[Dict]:
        """Adapters whose current/newest version is registered for a given
        agent_brain role ('action' / 'responder')."""
        return [a for a in self.list() if a.get("role", "action") == role]

    def find_by_capability(self, capability: str) -> List[Dict]:
        """Adapters whose current/newest version declares a given
        capability tag (e.g. 'sql', 'uk_slang'). Declarative lookup only —
        does not check base-model match or anything else."""
        return [a for a in self.list() if capability in (a.get("capabilities") or [])]

    def is_compatible(self, name_a: str, name_b: str) -> bool:
        """
        Declarative compatibility check between two adapters' current
        versions — consults compatible_with/incompatible_with, nothing
        else. There is no runtime yet that loads two adapters at once
        (no AdapterFusion-style combination implemented), so this has
        nothing to enforce against today; it exists so the contract is
        checkable once something does.
        """
        a = self.get(name_a)
        b = self.get(name_b)
        if a is None or b is None:
            return False
        if name_b in (a.get("incompatible_with") or []):
            return False
        if name_a in (b.get("incompatible_with") or []):
            return False
        return True
