"""Repo-local skill pack discovery, validation, and sync utilities."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

MAX_SKILL_NAME_LENGTH = 64
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

DISCLOSURE_METADATA = 1
DISCLOSURE_INSTRUCTIONS = 2
DISCLOSURE_RESOURCES = 3

AGENT_SKILL_TARGETS = {
    "codex": Path(".codex/skills"),
    "claude": Path(".claude/skills"),
    "claude-code": Path(".claude/skills"),
    "agy": Path(".gemini/antigravity/skills"),
    "antigravity": Path(".gemini/antigravity/skills"),
}


class SkillRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class SkillFrontmatter:
    name: str
    description: str
    license: Optional[str] = None
    compatibility: Optional[str] = None
    allowed_tools: Optional[List[str]] = None


@dataclass(frozen=True)
class SkillSpec:
    frontmatter: SkillFrontmatter
    path: Path
    instructions: str
    disclosure_level: int = DISCLOSURE_METADATA
    resource_files: Optional[Dict[str, List[str]]] = None
    remote_source: Optional[Dict[str, str]] = None

    @property
    def name(self) -> str:
        return self.frontmatter.name

    @property
    def description(self) -> str:
        return self.frontmatter.description

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        return data

    def with_instructions(self) -> "SkillSpec":
        return SkillSpec(
            frontmatter=self.frontmatter,
            path=self.path,
            instructions=self.instructions,
            disclosure_level=DISCLOSURE_INSTRUCTIONS,
            resource_files=self.resource_files,
            remote_source=self.remote_source,
        )

    def with_resources(self) -> "SkillSpec":
        return SkillSpec(
            frontmatter=self.frontmatter,
            path=self.path,
            instructions=self.instructions,
            disclosure_level=DISCLOSURE_RESOURCES,
            resource_files=catalog_resources(self.path),
            remote_source=self.remote_source,
        )


def validate_skill_name(name: str) -> None:
    if not name:
        raise SkillRegistryError("skill name is required")
    if len(name) > MAX_SKILL_NAME_LENGTH:
        raise SkillRegistryError(f"skill name exceeds {MAX_SKILL_NAME_LENGTH} chars")
    if not SKILL_NAME_RE.match(name):
        raise SkillRegistryError(
            "skill name must be lowercase alnum segments separated by single hyphens"
        )


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_scalar_or_inline_list(value: str) -> Any:
    value = _clean_scalar(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_clean_scalar(part) for part in inner.split(",")]
    return value


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillRegistryError("SKILL.md must start with YAML frontmatter")

    close_idx: Optional[int] = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            close_idx = idx
            break
    if close_idx is None:
        raise SkillRegistryError("SKILL.md is missing closing frontmatter delimiter")

    frontmatter: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in lines[1:close_idx]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if current_list_key and raw_line.startswith(" ") and stripped.startswith("- "):
            frontmatter.setdefault(current_list_key, []).append(_clean_scalar(stripped[2:]))
            continue
        if ":" not in raw_line:
            raise SkillRegistryError(f"invalid frontmatter line: {raw_line}")
        key, value = raw_line.split(":", 1)
        key = key.strip().replace("-", "_")
        value = value.strip()
        if not key:
            raise SkillRegistryError(f"invalid frontmatter line: {raw_line}")
        if value == "":
            frontmatter[key] = []
            current_list_key = key
        else:
            frontmatter[key] = _parse_scalar_or_inline_list(value)
            current_list_key = None

    body = "\n".join(lines[close_idx + 1 :]).strip()
    return frontmatter, body


def _string_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return None
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [part.strip() for part in text.split() if part.strip()]


def load_source_toml(skill_dir: Path) -> Optional[Dict[str, str]]:
    source_path = skill_dir / "SOURCE.toml"
    if not source_path.exists():
        return None
    try:
        from memory_os.core.toml_compat import load_toml_text

        data = load_toml_text(source_path.read_text(encoding="utf-8"))
        return {
            "repo": str(data.get("repo", "")).strip(),
            "ref": str(data.get("ref", "main")).strip(),
            "subdir": str(data.get("subdir", "")).strip(),
        }
    except Exception:
        return None


def load_skill(skill_dir: Path) -> SkillSpec:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(skill_md)
    frontmatter, body = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    validate_skill_name(name)
    if skill_dir.name != name:
        raise SkillRegistryError(
            f"directory name '{skill_dir.name}' does not match skill name '{name}'"
        )
    if not description:
        raise SkillRegistryError(f"{name}: description is required")
    fm = SkillFrontmatter(
        name=name,
        description=description,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        allowed_tools=_string_list(
            frontmatter.get("allowed_tools", frontmatter.get("allowedtools"))
        ),
    )
    # Validate commands/ folder
    commands_dir = skill_dir / "commands"
    if commands_dir.exists() and commands_dir.is_dir():
        for file in sorted(commands_dir.rglob("*")):
            if file.is_file():
                if not file.name.endswith(".md"):
                    raise SkillRegistryError(f"file '{file.relative_to(skill_dir)}' in commands/ must be a markdown file (*.md)")

    # Validate mcp/ folder
    mcp_dir = skill_dir / "mcp"
    if mcp_dir.exists() and mcp_dir.is_dir():
        for file in sorted(mcp_dir.rglob("*")):
            if file.is_file():
                if not file.name.endswith(".json"):
                    raise SkillRegistryError(f"file '{file.relative_to(skill_dir)}' in mcp/ must be a JSON file (*.json)")
                try:
                    json.loads(file.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise SkillRegistryError(f"file '{file.relative_to(skill_dir)}' in mcp/ is not valid JSON: {exc}")

    remote_source = load_source_toml(skill_dir)
    return SkillSpec(frontmatter=fm, path=skill_dir, instructions=body, remote_source=remote_source)


def discover_skills(root: Path, skills_dir: str = "skills") -> List[SkillSpec]:
    base = root / skills_dir
    if not base.exists():
        return []
    skills: List[SkillSpec] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "SKILL.md").exists():
            skills.append(load_skill(child))
    return skills


def validate_skills(root: Path, skills_dir: str = "skills") -> Dict[str, Any]:
    base = root / skills_dir
    errors: List[str] = []
    skills: List[Dict[str, Any]] = []
    if not base.exists():
        return {"ok": False, "skills": [], "errors": [f"{skills_dir}/ not found"]}

    for child in sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: p.name):
        if not (child / "SKILL.md").exists():
            errors.append(f"{child.relative_to(root)}: missing SKILL.md")
            continue
        try:
            skill = load_skill(child)
            skills.append(skill.to_dict())
        except Exception as exc:
            errors.append(f"{child.relative_to(root)}: {exc}")
    return {"ok": not errors, "skills": skills, "errors": errors}


def catalog_resources(skill_dir: Path) -> Dict[str, List[str]]:
    resources: Dict[str, List[str]] = {}
    for dirname in ("scripts", "references", "assets", "agents", "commands", "mcp"):
        directory = skill_dir / dirname
        if not directory.exists():
            continue
        files = [
            str(path.relative_to(directory))
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        ]
        if files:
            resources[dirname] = files
    return resources


def format_skill_context(skill: SkillSpec) -> str:
    lines = [f'<skill name="{skill.name}">']
    if skill.disclosure_level == DISCLOSURE_METADATA:
        lines.append(skill.description)
    else:
        lines.append(skill.instructions or skill.description)
    if skill.disclosure_level >= DISCLOSURE_RESOURCES and skill.resource_files:
        lines += ["", "### Available Resources"]
        for dirname, files in sorted(skill.resource_files.items()):
            lines.append(f"**{dirname}/**: {', '.join(files)}")
    lines.append("</skill>")
    return "\n".join(lines)


def _hash_skill_dir(skill_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(skill_dir).as_posix()
        if rel == ".DS_Store" or "/__pycache__/" in f"/{rel}/":
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _ignore_copy(_directory: str, names: Iterable[str]) -> List[str]:
    ignored = {".DS_Store", "__pycache__"}
    return [name for name in names if name in ignored]


def target_for_agent(root: Path, agent: str) -> Path:
    key = agent.strip().lower()
    if key not in AGENT_SKILL_TARGETS:
        supported = ", ".join(sorted(AGENT_SKILL_TARGETS))
        raise SkillRegistryError(f"unsupported agent '{agent}' (supported: {supported})")
    return root / AGENT_SKILL_TARGETS[key]


def sync_skills(
    root: Path,
    agents: Iterable[str],
    skills_dir: str = "skills",
    dry_run: bool = False,
) -> Dict[str, Any]:
    report = validate_skills(root, skills_dir=skills_dir)
    if not report["ok"]:
        return {"ok": False, "actions": [], "errors": report["errors"]}

    skills = discover_skills(root, skills_dir=skills_dir)
    actions: List[Dict[str, Any]] = []
    
    # Read existing lock to preserve synced_agent_dirs
    lock_path = root / "memory" / "skills.lock.json"
    existing_skills = {}
    if lock_path.exists():
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            existing_skills = data.get("skills", {})
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    skills_dict = {}
    # Pre-populate with existing lock to preserve other skills
    for name, info in existing_skills.items():
        skills_dict[name] = {
            "source": info.get("source", f"{skills_dir}/{name}"),
            "hash": info.get("hash", ""),
            "synced_agent_dirs": info.get("synced_agent_dirs", [])
        }

    for agent in agents:
        target_base = target_for_agent(root, agent)
        for skill in skills:
            destination = target_base / skill.name
            dest_rel = str(destination.relative_to(root))
            h = _hash_skill_dir(skill.path)
            
            action = {
                "agent": agent,
                "skill": skill.name,
                "destination": dest_rel,
                "hash": h,
                "status": "would_sync" if dry_run else "synced",
            }
            actions.append(action)
            if dry_run:
                continue
            target_base.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(skill.path, destination, ignore=_ignore_copy)
            
            # Update local skill manifest record
            source_rel = str(skill.path.relative_to(root))
            skill_info = skills_dict.setdefault(skill.name, {
                "source": source_rel,
                "hash": h,
                "synced_agent_dirs": []
            })
            skill_info["hash"] = h
            skill_info["source"] = source_rel
            if dest_rel not in skill_info["synced_agent_dirs"]:
                skill_info["synced_agent_dirs"].append(dest_rel)

    if not dry_run:
        # Sort synced_agent_dirs for determinism
        for name, info in skills_dict.items():
            info["synced_agent_dirs"] = sorted(list(set(info["synced_agent_dirs"])))
            
        lock_payload = {
            "version": 1,
            "skills": skills_dict
        }
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(lock_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        inject_skills_into_agents_md(root, skills)

    return {"ok": True, "actions": actions, "errors": []}


def inject_skills_into_agents_md(root: Path, skills: List[SkillSpec]) -> None:
    agents_md_path = root / "AGENTS.md"
    if not agents_md_path.exists():
        return
        
    lines = []
    lines.append("<!-- MEMORY_OS SKILLS BLOCK START (auto-generated, do not edit by hand) -->")
    lines.append("## Available Agent Skills")
    lines.append("")
    lines.append("You have access to the following repo-local skill packs under `skills/`:")
    for skill in sorted(skills, key=lambda s: s.name):
        lines.append(f"- **{skill.name}**: {skill.description}")
    lines.append("")
    lines.append("To check, sync, or lock skills, use `memory_os skills` commands.")
    lines.append("<!-- MEMORY_OS SKILLS BLOCK END -->")
    block_text = "\n".join(lines)
    
    content = agents_md_path.read_text(encoding="utf-8")
    
    start_marker = "<!-- MEMORY_OS SKILLS BLOCK START (auto-generated, do not edit by hand) -->"
    end_marker = "<!-- MEMORY_OS SKILLS BLOCK END -->"
    
    if start_marker in content and end_marker in content:
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker) + len(end_marker)
        new_content = content[:start_idx] + block_text + content[end_idx:]
    else:
        new_content = content.rstrip() + "\n\n" + block_text + "\n"
        
    agents_md_path.write_text(new_content, encoding="utf-8")


def write_skills_lock(root: Path, skills_dir: str = "skills") -> Dict[str, Any]:
    report = validate_skills(root, skills_dir=skills_dir)
    if not report["ok"]:
        return {"ok": False, "errors": report["errors"]}

    skills = discover_skills(root, skills_dir=skills_dir)
    
    # Read existing lock to preserve synced_agent_dirs
    lock_path = root / "memory" / "skills.lock.json"
    existing_skills = {}
    if lock_path.exists():
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            existing_skills = data.get("skills", {})
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    skills_dict = {}
    for skill in skills:
        source_rel = str(skill.path.relative_to(root))
        h = _hash_skill_dir(skill.path)
        
        # Preserve synced_agent_dirs from existing lock
        existing_info = existing_skills.get(skill.name, {})
        synced_agent_dirs = existing_info.get("synced_agent_dirs", [])
        if not isinstance(synced_agent_dirs, list):
            synced_agent_dirs = []
            
        skills_dict[skill.name] = {
            "source": source_rel,
            "hash": h,
            "synced_agent_dirs": sorted(list(set(synced_agent_dirs)))
        }

    lock_payload = {
        "version": 1,
        "skills": skills_dict
    }

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "skills": skills_dict, "errors": []}


def refresh_skill(root: Path, skill_name: str, skills_dir: str = "skills") -> Dict[str, Any]:
    import subprocess
    import tempfile
    
    skill_dir = root / skills_dir / skill_name
    if not skill_dir.exists():
        raise SkillRegistryError(f"Skill '{skill_name}' directory not found")
        
    source_info = load_source_toml(skill_dir)
    if not source_info:
        raise SkillRegistryError(f"SOURCE.toml absent in skill '{skill_name}'")
        
    if not shutil.which("git"):
        raise SkillRegistryError("git command is missing on the system")
        
    repo = source_info["repo"]
    ref = source_info["ref"]
    subdir = source_info["subdir"]
    
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        
        try:
            subprocess.run(
                ["git", "clone", repo, "."],
                cwd=temp_dir,
                capture_output=True,
                check=True,
                text=True
            )
            subprocess.run(
                ["git", "checkout", ref],
                cwd=temp_dir,
                capture_output=True,
                check=True,
                text=True
            )
            res_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=temp_dir,
                capture_output=True,
                check=True,
                text=True
            )
            resolved_sha = res_sha.stdout.strip()
        except subprocess.CalledProcessError as exc:
            raise SkillRegistryError(f"Git execution failed: {exc.stderr.strip()}")
            
        src_path = temp_dir / subdir if subdir else temp_dir
        if not src_path.exists():
            raise SkillRegistryError(f"Subdir '{subdir}' not found in remote repository")
            
        source_toml_content = (skill_dir / "SOURCE.toml").read_text(encoding="utf-8")
        
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        (skill_dir / "SOURCE.toml").write_text(source_toml_content, encoding="utf-8")
        
        for item in src_path.iterdir():
            if item.name == "SOURCE.toml":
                continue
            dest_item = skill_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest_item, ignore=_ignore_copy)
            else:
                shutil.copy2(item, dest_item)
                
        lock_path = root / "memory" / "skills.lock.json"
        lock_data = {"version": 1, "skills": {}}
        if lock_path.exists():
            try:
                lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)
                
        skills_dict = lock_data.setdefault("skills", {})
        h = _hash_skill_dir(skill_dir)
        skill_info = skills_dict.setdefault(skill_name, {
            "source": f"{skills_dir}/{skill_name}",
            "hash": h,
            "synced_agent_dirs": []
        })
        skill_info["hash"] = h
        skill_info["resolved_ref"] = resolved_sha
        
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(lock_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8"
        )
        
        return {
            "ok": True,
            "resolved_ref": resolved_sha,
            "hash": h
        }


def refresh_all_skills(root: Path, skills_dir: str = "skills") -> Dict[str, Any]:
    base = root / skills_dir
    if not base.exists():
        return {"ok": True, "refreshed": {}, "errors": []}
        
    refreshed = {}
    errors = []
    
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "SOURCE.toml").exists():
            try:
                res = refresh_skill(root, child.name, skills_dir=skills_dir)
                refreshed[child.name] = res
            except Exception as e:
                errors.append(f"{child.name}: {e}")
                
    if errors:
        return {"ok": False, "refreshed": refreshed, "errors": errors}
    return {"ok": True, "refreshed": refreshed, "errors": []}
