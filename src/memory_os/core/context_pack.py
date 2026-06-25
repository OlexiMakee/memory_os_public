import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.file_policy import classify_private_path, load_export_ignore_patterns
from memory_os.core.safe_id import confine_to_root
from memory_os.modules.context import ContextRegistry
from memory_os.modules.search import MemorySearcher


class ContextPackBuilder:
    """Builder for context packaging in Memory OS."""

    # Total token_estimate budget across all relevant_files combined. Without this,
    # a handful of large but keyword-matching docs (e.g. this repo's own multi-thousand
    # line strategy/encyclopedia files) can make a "targeted" pack bigger than the
    # whole-repo dump it exists to replace.
    DEFAULT_MAX_TOTAL_TOKENS = 8000

    def __init__(self, config: MemoryOSConfig):
        self.config = config

    def build(
        self,
        task: str = "",
        contract_path: Optional[str] = None,
        paths: Optional[List[str]] = None,
        max_total_tokens: Optional[int] = DEFAULT_MAX_TOTAL_TOKENS,
        include_private: bool = False,
    ) -> Dict[str, Any]:
        """Builds a context pack for the given task and configuration.

        `max_total_tokens` caps the combined token_estimate of relevant_files; files
        that would push the pack over budget are moved to excluded_noise (reason
        "over-budget") instead, highest relevance_score kept first. Pass None to
        disable the cap.

        Returns a dict with keys:
        - task_summary
        - relevant_files
        - relevant_memory_nodes
        - constraints
        - excluded_noise
        - verification_plan
        """
        # 1. Ingest & Parse Contract — redact here, once, regardless of which
        # parse branch (JSON vs markdown/text) produced these fields.
        contract_data = self._parse_contract(contract_path)
        task_summary = ContextRegistry.redact(contract_data["task_summary"] or "")
        if not task_summary:
            task_summary = task

        constraints = [ContextRegistry.redact(c) for c in contract_data["constraints"]]
        verification_plan = [ContextRegistry.redact(v) for v in contract_data["verification_plan"]]

        # Relevance keywords: prefer the explicit task string, but fall back to
        # the contract's own text so `context build --contract ...` (no --task)
        # still scores files instead of excluding everything as irrelevant.
        keyword_source = task or task_summary or " ".join(constraints + verification_plan)

        # Normalize paths
        if paths is None:
            paths = ["."]
        elif isinstance(paths, (str, Path)):
            paths = [str(paths)]
        else:
            paths = [str(p) for p in paths]

        # 2. Collect Candidates
        registry = ContextRegistry(str(self.config.root_dir))
        export_ignore_patterns = load_export_ignore_patterns(self.config.root_dir)
        snapshot = registry.build_snapshot(paths=paths, exclude_private=not include_private)

        # 3. Analyze and Sort Files (secret guard + relevance)
        relevant_files = []
        excluded_noise = []

        # Keywords for relevance scoring
        keywords = [w for w in re.findall(r"\w+", keyword_source.lower()) if len(w) >= 2]

        for skipped in snapshot.get("skipped", []):
            excluded_noise.append(
                {
                    "file": skipped.get("file", ""),
                    "reason": skipped.get("reason", "skipped"),
                    "token_estimate": 0,
                }
            )

        for item in snapshot.get("items", []):
            meta = item.get("meta", {})
            filepath = meta.get("file", "")
            filepath_lower = filepath.lower()

            policy_reason = None
            if not include_private:
                policy_reason = classify_private_path(
                    filepath,
                    export_ignore_patterns=export_ignore_patterns,
                )

            if policy_reason:
                excluded_noise.append(
                    {
                        "file": filepath,
                        "reason": policy_reason,
                        "token_estimate": 0,
                    }
                )
                continue

            full_path = self.config.root_dir / filepath
            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                content = ""

            # Check if redact changes content (secret-bearing)
            redacted_content = ContextRegistry.redact(content)
            token_estimate = len(redacted_content) // 4

            if redacted_content != content:
                excluded_noise.append(
                    {
                        "file": filepath,
                        "reason": "secret-bearing",
                        "token_estimate": token_estimate,
                    }
                )
                continue

            # Score relevance
            score = 0
            if keywords:
                # Filename match
                for kw in keywords:
                    if kw in filepath_lower:
                        score += 10
                # Symbols match (functions, classes, routes)
                for sym in (
                    meta.get("functions", [])
                    + meta.get("classes", [])
                    + meta.get("routes", [])
                ):
                    sym_lower = str(sym).lower()
                    for kw in keywords:
                        if kw in sym_lower:
                            score += 5
                # Headings match
                for heading in meta.get("headings", []):
                    heading_lower = str(heading).lower()
                    for kw in keywords:
                        if kw in heading_lower:
                            score += 3
                # Content match — capped per keyword so one large/repetitive file
                # (e.g. a JSONL graph dump) cannot outrank genuinely relevant,
                # smaller files just by sheer repetition count.
                content_lower = redacted_content.lower()
                for kw in keywords:
                    score += min(content_lower.count(kw), 5)

            if score == 0:
                excluded_noise.append(
                    {
                        "file": filepath,
                        "reason": "irrelevant",
                        "token_estimate": token_estimate,
                    }
                )
            else:
                relevant_files.append(
                    {
                        "file": filepath,
                        "content": redacted_content,
                        "token_estimate": token_estimate,
                        "relevance_score": score,
                    }
                )

        # 4. Retrieve Memory Nodes
        relevant_memory_nodes = []
        searcher = MemorySearcher(self.config)
        try:
            search_results = searcher.search_memory(keyword_source)
        except Exception:
            search_results = []

        for node in search_results:
            # We want memory nodes, which are non-code_file type
            if node.get("type") == "code_file":
                continue

            node_id = str(node.get("id", ""))
            summary = str(node.get("summary", ""))
            tags = node.get("tags", [])
            node_type = str(node.get("type", ""))

            matched_kws = []
            for kw in keywords:
                if (
                    kw in node_id.lower()
                    or kw in summary.lower()
                    or kw in node_type.lower()
                    or any(kw in str(t).lower() for t in tags)
                ):
                    matched_kws.append(kw)

            if matched_kws:
                reason = f"Matches task keyword(s): {', '.join(matched_kws)}"
            else:
                reason = "Retrieved via graph traversal or fallback matching"

            node_copy = dict(node)
            if "summary" in node_copy:
                node_copy["summary"] = ContextRegistry.redact(str(node_copy["summary"]))
            if "tags" in node_copy and isinstance(node_copy["tags"], list):
                node_copy["tags"] = [ContextRegistry.redact(str(t)) for t in node_copy["tags"]]
            node_copy["reason"] = reason
            relevant_memory_nodes.append(node_copy)

        # 4b. Enforce total token budget: keep highest-scored files first, push the
        # rest to excluded_noise rather than silently returning an unbounded pack.
        if max_total_tokens is not None:
            relevant_files.sort(key=lambda x: (-x["relevance_score"], x["file"]))
            kept = []
            running_total = 0
            for f in relevant_files:
                if kept and running_total + f["token_estimate"] > max_total_tokens:
                    excluded_noise.append(
                        {
                            "file": f["file"],
                            "reason": "over-budget",
                            "token_estimate": f["token_estimate"],
                        }
                    )
                    continue
                running_total += f["token_estimate"]
                kept.append(f)
            relevant_files = kept

        # 5. Enforce Stable Ordering
        relevant_files.sort(key=lambda x: x["file"])
        excluded_noise.sort(key=lambda x: x["file"])
        relevant_memory_nodes.sort(key=lambda x: x.get("id", ""))

        return {
            "task_summary": task_summary,
            "relevant_files": relevant_files,
            "relevant_memory_nodes": relevant_memory_nodes,
            "constraints": constraints,
            "excluded_noise": excluded_noise,
            "verification_plan": verification_plan,
        }

    def to_markdown(self, pack: Dict[str, Any]) -> str:
        """Renders clean Markdown sections with headings matching those six names."""
        lines = []

        # Heading 1: task_summary
        lines.append("## task_summary")
        lines.append(pack.get("task_summary") or "")
        lines.append("")

        # Heading 2: relevant_files
        lines.append("## relevant_files")
        relevant_files = pack.get("relevant_files") or []
        if not relevant_files:
            lines.append("No relevant files identified.")
        else:
            for f in relevant_files:
                file_path = f.get("file", "")
                tokens = f.get("token_estimate", 0)
                score = f.get("relevance_score", 0)
                content = f.get("content", "")
                lines.append(f"### {file_path}")
                lines.append(f"- **Token Estimate**: {tokens}")
                lines.append(f"- **Relevance Score**: {score}")
                lines.append("")
                suffix = Path(file_path).suffix.lstrip(".")
                lines.append(f"```{suffix}")
                lines.append(content)
                lines.append("```")
                lines.append("")
        lines.append("")

        # Heading 3: relevant_memory_nodes
        lines.append("## relevant_memory_nodes")
        nodes = pack.get("relevant_memory_nodes") or []
        if not nodes:
            lines.append("No relevant memory nodes found.")
        else:
            for node in nodes:
                node_id = node.get("id", "")
                node_type = node.get("type", "")
                reason = node.get("reason", "")
                summary = node.get("summary", "")
                tags = ", ".join(node.get("tags") or [])
                lines.append(f"### {node_id}")
                lines.append(f"- **Type**: {node_type}")
                lines.append(f"- **Reason**: {reason}")
                if tags:
                    lines.append(f"- **Tags**: {tags}")
                lines.append(f"- **Summary**: {summary}")
                lines.append("")
        lines.append("")

        # Heading 4: constraints
        lines.append("## constraints")
        constraints = pack.get("constraints") or []
        if not constraints:
            lines.append("No constraints specified.")
        else:
            for c in constraints:
                lines.append(f"- {c}")
        lines.append("")

        # Heading 5: excluded_noise
        lines.append("## excluded_noise")
        excluded = pack.get("excluded_noise") or []
        if not excluded:
            lines.append("No files excluded as noise.")
        else:
            for ex in excluded:
                file_path = ex.get("file", "")
                reason = ex.get("reason", "")
                tokens = ex.get("token_estimate", 0)
                lines.append(
                    f"- **{file_path}**: {reason} ({tokens} estimated tokens)"
                )
        lines.append("")

        # Heading 6: verification_plan
        lines.append("## verification_plan")
        vp = pack.get("verification_plan") or []
        if not vp:
            lines.append("No verification plan specified.")
        else:
            for v in vp:
                lines.append(f"- {v}")
        lines.append("")

        return "\n".join(lines)

    def _parse_contract(self, contract_path: Optional[str]) -> Dict[str, Any]:
        task_summary = ""
        constraints = []
        verification_plan = []

        if not contract_path:
            return {
                "task_summary": task_summary,
                "constraints": constraints,
                "verification_plan": verification_plan,
            }

        try:
            path = confine_to_root(contract_path, self.config.root_dir)
        except ValueError:
            # Path resolves outside the project root — treat like "not found"
            # rather than reading an arbitrary local file.
            return {
                "task_summary": task_summary,
                "constraints": constraints,
                "verification_plan": verification_plan,
            }
        if not path.exists():
            return {
                "task_summary": task_summary,
                "constraints": constraints,
                "verification_plan": verification_plan,
            }

        content = path.read_text(encoding="utf-8", errors="ignore").strip()

        # Try JSON parsing
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                task_summary = (
                    data.get("task_summary") or data.get("objective") or ""
                )

                raw_constraints = data.get("constraints") or []
                if isinstance(raw_constraints, list):
                    constraints = [
                        str(c).strip()
                        for c in raw_constraints
                        if str(c).strip()
                    ]
                elif isinstance(raw_constraints, str):
                    constraints = [
                        c.strip()
                        for c in raw_constraints.split("\n")
                        if c.strip()
                    ]

                raw_vp = (
                    data.get("verification_plan")
                    or data.get("required_verification")
                    or []
                )
                if isinstance(raw_vp, list):
                    verification_plan = [
                        str(v).strip() for v in raw_vp if str(v).strip()
                    ]
                elif isinstance(raw_vp, str):
                    verification_plan = [
                        v.strip() for v in raw_vp.split("\n") if v.strip()
                    ]

                return {
                    "task_summary": task_summary,
                    "constraints": constraints,
                    "verification_plan": verification_plan,
                }
        except json.JSONDecodeError:
            pass

        # Parse markdown/text with regex
        # Constraints heading
        constraints_match = re.search(
            r"(?i)(?:^|\n)#+\s*Constraints\s*\n(.*?)(?=\n#+|$)",
            content,
            re.DOTALL,
        )
        if constraints_match:
            c_text = constraints_match.group(1).strip()
            constraints = self._clean_bullets(c_text)

        # Verification heading
        vp_match = re.search(
            r"(?i)(?:^|\n)#+\s*(?:Verification\s+Plan|Required\s+Verification)\s*\n(.*?)(?=\n#+|$)",
            content,
            re.DOTALL,
        )
        if vp_match:
            vp_text = vp_match.group(1).strip()
            verification_plan = self._clean_bullets(vp_text)

        # Task summary heading
        ts_match = re.search(
            r"(?i)(?:^|\n)#+\s*(?:Task\s+Summary|Objective)\s*\n(.*?)(?=\n#+|$)",
            content,
            re.DOTALL,
        )
        if ts_match:
            task_summary = ts_match.group(1).strip()
        else:
            first_heading = content.find("#")
            if first_heading > 0:
                task_summary = content[:first_heading].strip()
            elif first_heading == -1:
                task_summary = content

        return {
            "task_summary": task_summary,
            "constraints": constraints,
            "verification_plan": verification_plan,
        }

    def _clean_bullets(self, text: str) -> List[str]:
        lines = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"^(?:[-*+]\s*|\d+\.\s*)", "", line).strip()
            if cleaned:
                lines.append(cleaned)
        return lines
