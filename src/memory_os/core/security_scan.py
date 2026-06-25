import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.file_policy import unique_existing_files

# Regex patterns for detecting secrets
RE_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")
RE_PGP_PRIVATE_KEY = re.compile(r"-----BEGIN PGP PRIVATE KEY BLOCK-----")
RE_AWS_KEY = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
RE_SK_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")
RE_GITHUB_TOKEN = re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{36,})\b")

RE_CONN_STRINGS = [
    re.compile(r"postgresql://[^:]+:([^@\s]+)@[^\s]+"),
    re.compile(r"mongodb(?:\+srv)?://[^:]+:([^@\s]+)@[^\s]+"),
    re.compile(r"amqp://[^:]+:([^@\s]+)@[^\s]+"),
]

RE_ASSIGNMENTS = re.compile(
    r"(?i)(client_secret|access_token|refresh_token|private_key|api[_-]?key|auth_key|password|passwd|token|secret)"
    r"[a-zA-Z0-9_-]*"
    r"['\"]?\s*[:=]\s*['\"]?([^\s'\"',}]+)"
)

RE_BEARER = re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-\.\~]{10,})")

PROMPT_INJECTION_PHRASES = [
    "ignore previous instructions",
    "disregard the above",
    "you are now",
    "system prompt:",
    "new instructions:"
]

def is_placeholder(val: str) -> bool:
    """Check if the matched value is a placeholder or already redacted."""
    v = val.strip().lower().strip("'\"")
    if v in {
        "", "null", "none", "true", "false", "undefined",
        "[redacted]", "redacted", "placeholder", "your_api_key",
        "your-api-key", "your_token", "your-token", "your_password",
        "test", "dummy", "xxxxxx", "xxxx-xxxx-xxxx"
    }:
        return True
    if "[redacted" in v:
        return True
    return False

class SecurityScanner:
    """Offline security scanner for Memory OS local stores."""

    VALID_PROFILES = {"default", "private-docs", "context-artifacts", "docs", "all"}

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def scan(self, profile: str = "default") -> Dict[str, Any]:
        """Scan local-first stores for secret leakage and prompt-injection markers."""
        if profile not in self.VALID_PROFILES:
            raise ValueError(f"unsupported security scan profile: {profile}")

        scanned_files: List[str] = []
        findings: List[Dict[str, Any]] = []

        files_to_scan = self._collect_files(profile=profile)

        for file_path in files_to_scan:
            try:
                rel_path = str(file_path.relative_to(self.config.root_dir))
            except ValueError:
                rel_path = str(file_path)

            if not file_path.exists():
                continue

            scanned_files.append(rel_path)

            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_idx, line in enumerate(f, 1):
                        line_findings = self._scan_line(line, rel_path, line_idx)
                        findings.extend(line_findings)
            except Exception:
                # Skip gracefully if reading file fails
                pass

        # Deduplicate findings on the same line to avoid multiple identical entries
        # but keep unique categories/patterns
        unique_findings = []
        seen = set()
        for f in findings:
            key = (f["file"], f["line"], f["category"], f["pattern"])
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        secret_count = sum(1 for f in unique_findings if f["category"] == "secret")
        injection_marker_count = sum(1 for f in unique_findings if f["category"] == "prompt_injection")

        return {
            "scanned_files": scanned_files,
            "profile": profile,
            "findings": unique_findings,
            "secret_count": secret_count,
            "injection_marker_count": injection_marker_count
        }

    def _collect_files(self, profile: str = "default") -> List[Path]:
        files: List[Path] = []
        root = self.config.root_dir

        def add_default() -> None:
            memory_dir = root / "memory"
            if memory_dir.is_dir():
                files.extend(p for p in memory_dir.glob("*.jsonl") if p.is_file())

            capsules_file = root / "agent_context" / "task_capsules.jsonl"
            if capsules_file.is_file():
                files.append(capsules_file)

            evidence_dir = root / "agent_context" / "evidence"
            if evidence_dir.is_dir():
                files.extend(p for p in evidence_dir.glob("**/bundle.json") if p.is_file())

            packs_dir = root / "agent_context" / "context_packs"
            if packs_dir.is_dir():
                files.extend(p for p in packs_dir.glob("**/pack.json") if p.is_file())

        def add_private_docs() -> None:
            for rel in ("DEV_STRATEGY.md", "agent_context/IMPORTANT_PROPOSAL.md"):
                p = root / rel
                if p.is_file():
                    files.append(p)
            agent_context = root / "agent_context"
            if agent_context.is_dir():
                files.extend(p for p in agent_context.glob("**/*.md") if p.is_file())

        def add_context_artifacts() -> None:
            agent_context = root / "agent_context"
            if agent_context.is_dir():
                for pattern in (
                    "context_packs/**/*.json",
                    "context_packs/**/*.md",
                    "evidence/**/*.json",
                    "evidence/**/*.md",
                    "review_packs/**/*.json",
                    "review_packs/**/*.md",
                ):
                    files.extend(p for p in agent_context.glob(pattern) if p.is_file())

        def add_docs() -> None:
            for rel in ("README.md", "INDEX.md"):
                p = root / rel
                if p.is_file():
                    files.append(p)
            docs_roots = [root / "src" / "memory_os" / "docs", root / "templates"]
            for docs_root in docs_roots:
                if docs_root.is_dir():
                    files.extend(p for p in docs_root.glob("**/*.md") if p.is_file())

        if profile in {"default", "all"}:
            add_default()
        if profile in {"private-docs", "all"}:
            add_private_docs()
        if profile in {"context-artifacts", "all"}:
            add_context_artifacts()
        if profile in {"docs", "all"}:
            add_docs()

        return unique_existing_files(files)

    def _scan_line(self, line: str, file_rel_path: str, line_num: int) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        is_json = False
        obj = None
        try:
            # Strip potential leading/trailing commas or brackets if it's parts of multi-line JSON,
            # but try to parse as JSON first
            obj = json.loads(line.strip().rstrip(","))
            is_json = True
        except Exception:
            pass

        # 1. Check for .env file reference in payload path or any path fields
        if is_json and isinstance(obj, dict):
            env_val = self._find_env_file_in_paths(obj)
            if env_val:
                findings.append({
                    "file": file_rel_path,
                    "line": line_num,
                    "category": "secret",
                    "pattern": "env_file_in_path",
                    "excerpt": self._redact(line)
                })

            # Check prompt injection in free-text fields
            free_texts = self._extract_free_texts(obj)
            for text in free_texts:
                if self._check_prompt_injection(text):
                    findings.append({
                        "file": file_rel_path,
                        "line": line_num,
                        "category": "prompt_injection",
                        "pattern": "prompt_injection_marker",
                        "excerpt": self._redact(line)
                    })
        else:
            # Fallback/General check on the raw line text
            if ".env" in line:
                # If path/file indicators are in line and it mentions .env
                if any(ind in line.lower() for ind in ["path", "file", "payload", "evidence"]):
                    findings.append({
                        "file": file_rel_path,
                        "line": line_num,
                        "category": "secret",
                        "pattern": "env_file_in_path",
                        "excerpt": self._redact(line)
                    })

            if self._check_prompt_injection(line):
                findings.append({
                    "file": file_rel_path,
                    "line": line_num,
                    "category": "prompt_injection",
                    "pattern": "prompt_injection_marker",
                    "excerpt": self._redact(line)
                })

        # 2. Check secret patterns on raw line
        secret_matches = self._scan_raw_line_for_secrets(line)
        for sm in secret_matches:
            findings.append({
                "file": file_rel_path,
                "line": line_num,
                "category": "secret",
                "pattern": sm["pattern"],
                "excerpt": self._redact(line)
            })

        return findings

    def _find_env_file_in_paths(self, obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_lower = k.lower()
                if ("path" in k_lower or "file" in k_lower or "evidence" in k_lower) and isinstance(v, str):
                    filename = os.path.basename(v)
                    if filename == ".env" or filename.startswith(".env.") or ".env" in filename:
                        return v
                elif isinstance(v, list) and ("path" in k_lower or "file" in k_lower or "evidence" in k_lower):
                    for item in v:
                        if isinstance(item, str):
                            filename = os.path.basename(item)
                            if filename == ".env" or filename.startswith(".env.") or ".env" in filename:
                                return item
                else:
                    res = self._find_env_file_in_paths(v)
                    if res:
                        return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._find_env_file_in_paths(item)
                if res:
                    return res
        return None

    def _extract_free_texts(self, obj: Any) -> List[str]:
        strings = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in {
                    "id", "type", "status", "freshness", "trust", "domain",
                    "created_by_protocol", "required_verification_protocol"
                }:
                    continue
                strings.extend(self._extract_free_texts(v))
        elif isinstance(obj, list):
            for item in obj:
                strings.extend(self._extract_free_texts(item))
        elif isinstance(obj, str):
            strings.append(obj)
        return strings

    def _check_prompt_injection(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for phrase in PROMPT_INJECTION_PHRASES:
            if phrase in text_lower:
                return phrase
        return None

    def _scan_raw_line_for_secrets(self, line: str) -> List[Dict[str, Any]]:
        findings = []

        # 1. Private key blocks
        if RE_PRIVATE_KEY.search(line) or RE_PGP_PRIVATE_KEY.search(line):
            findings.append({"pattern": "private_key_block"})

        # 2. AWS key
        for m in RE_AWS_KEY.findall(line):
            if not is_placeholder(m):
                findings.append({"pattern": "aws_access_key"})
                break

        # 3. OpenAI/sk-token
        for m in RE_SK_TOKEN.findall(line):
            if not is_placeholder(m):
                findings.append({"pattern": "sk_token"})
                break

        # 4. GitHub tokens
        for m in RE_GITHUB_TOKEN.findall(line):
            if not is_placeholder(m):
                findings.append({"pattern": "github_token"})
                break

        # 5. Bearer tokens
        for match in RE_BEARER.finditer(line):
            token_val = match.group(1)
            if not is_placeholder(token_val) and len(token_val) >= 4:
                findings.append({"pattern": "bearer_token"})
                break

        # 6. Connection strings
        for re_conn in RE_CONN_STRINGS:
            matched = False
            for match in re_conn.finditer(line):
                passwd = match.group(1)
                if not is_placeholder(passwd) and len(passwd) >= 4:
                    findings.append({"pattern": "connection_string_password"})
                    matched = True
                    break
            if matched:
                break

        # 7. Assignments
        for match in RE_ASSIGNMENTS.finditer(line):
            key = match.group(1)
            val = match.group(2)
            if not is_placeholder(val) and len(val) >= 4:
                findings.append({"pattern": f"assignment_{key.lower()}"})

        return findings

    def _redact(self, line: str) -> str:
        redacted = line

        # Redact private key block
        redacted = RE_PRIVATE_KEY.sub("[REDACTED PRIVATE KEY HEADER]", redacted)
        redacted = RE_PGP_PRIVATE_KEY.sub("[REDACTED PRIVATE KEY HEADER]", redacted)

        # Redact AWS key
        for m in RE_AWS_KEY.findall(redacted):
            if not is_placeholder(m):
                redacted = redacted.replace(m, "[REDACTED]")

        # Redact SK token
        for m in RE_SK_TOKEN.findall(redacted):
            if not is_placeholder(m):
                redacted = redacted.replace(m, "[REDACTED]")

        # Redact GitHub token
        for m in RE_GITHUB_TOKEN.findall(redacted):
            if not is_placeholder(m):
                redacted = redacted.replace(m, "[REDACTED]")

        # Redact Bearer token
        for match in RE_BEARER.finditer(redacted):
            token_val = match.group(1)
            if not is_placeholder(token_val):
                redacted = redacted.replace(token_val, "[REDACTED]")

        # Redact Connection string passwords
        for re_conn in RE_CONN_STRINGS:
            for match in re_conn.finditer(redacted):
                passwd = match.group(1)
                if not is_placeholder(passwd):
                    redacted = redacted.replace(passwd, "[REDACTED]")

        # Redact Assignments
        for match in RE_ASSIGNMENTS.finditer(redacted):
            val = match.group(2)
            if not is_placeholder(val):
                redacted = redacted.replace(val, "[REDACTED]")

        # Redact .env paths
        redacted = re.sub(r"['\"][^'\"]*\.env[^'\"]*['\"]", '"[REDACTED]"', redacted)
        redacted = re.sub(r"[a-zA-Z0-9_\-\./]*\.env[a-zA-Z0-9_\-\.]*", "[REDACTED]", redacted)

        return redacted.strip()
