"""
Transcript Ingestor

Parses AI IDE session logs (e.g. transcript.jsonl) and uses LLM to 
extract completed tasks into task_capsules.jsonl.
"""

import json
from collections import deque
from pathlib import Path
from typing import List, Dict, Any, Optional

from memory_os.core.config import MemoryOSConfig
from memory_os.core.llm_service import DefaultLlmProviderService
from memory_os.core.prompt_formatter import wrap_in_xml
from memory_os.core.budget import BudgetManager
from memory_os.core.alerts import AlertManager

SYSTEM_PROMPT = """
You are a Memory OS agent observing a developer's AI IDE session transcript.
Your job is to identify what tasks were completely resolved in this session and extract them into a JSON array of task capsules.

A task capsule must look like this:
{
  "task": "Short description of what was done",
  "outcome": "Brief description of the resolution or implementation",
  "files_changed": ["list", "of", "files"],
  "workflow": "product" or "memory_os",
  "status": "done"
}

Read the transcript provided below. Focus only on the actual implementation steps that were explicitly completed.
Output ONLY valid JSON containing a list of task capsules. If no tasks were completed, output an empty list [].
"""

USER_TEMPLATE = """
<transcript>
{transcript}
</transcript>
"""

class TranscriptIngestor:
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.llm = DefaultLlmProviderService()
        self.budget = BudgetManager(config)
        self.alerts = AlertManager(config)

    def parse_transcript(self, transcript_path: Path, max_lines: int = 200) -> str:
        """Reads transcript.jsonl and builds a readable conversation log."""
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript not found: {transcript_path}")
            
        # Bounded rolling buffer instead of reading the whole file into memory
        # — a multi-GB transcript would otherwise OOM here.
        recent_lines: "deque[str]" = deque(maxlen=max_lines)
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                recent_lines.append(line)

        convo = []
        for line in recent_lines:
            try:
                data = json.loads(line)
                step_type = data.get("type", "UNKNOWN")
                content = data.get("content", "")
                if not content:
                    continue
                if not isinstance(content, str):
                    content = str(content)
                # Truncate very long outputs (like view_file results)
                if len(content) > 1000:
                    content = content[:1000] + "... [TRUNCATED]"
                convo.append(f"[{step_type}]: {content}")
            except json.JSONDecodeError:
                continue

        return "\n\n".join(convo)

    def ingest(self, transcript_path: Path, provider: Optional[str] = None, model: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parses the transcript, extracts capsules via LLM, and appends to task_capsules.jsonl."""
        if self.budget.is_budget_exhausted():
            self.alerts.send_alert("Memory OS Budget Exhausted", "TranscriptIngestor skipped because max_daily_tokens was reached.", is_critical=True)
            return []

        transcript_text = self.parse_transcript(transcript_path)
        if not transcript_text:
            return []
            
        user_message = USER_TEMPLATE.format(transcript=transcript_text)
        
        # Estimate token cost (rough heuristic: 1 token = 4 chars)
        estimated_cost = (len(SYSTEM_PROMPT) + len(user_message)) // 4
        self.budget.add_usage(estimated_cost)
        
        result_text = self.llm.call_llm(
            user_message=user_message,
            system_prompt=SYSTEM_PROMPT,
            provider=provider,
            model=model
        )
        
        try:
            # Try to parse the JSON output from the LLM
            start_idx = result_text.find('[')
            end_idx = result_text.rfind(']') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = result_text[start_idx:end_idx]
                capsules = json.loads(json_str)
            else:
                capsules = []
        except Exception:
            return []
            
        # Validate and write to task_capsules.jsonl
        valid_capsules = []
        for c in capsules:
            if isinstance(c, dict) and "task" in c and "status" in c:
                c.setdefault("workflow", "product")
                valid_capsules.append(c)
                
        if valid_capsules:
            self._append_capsules(valid_capsules)
            
        return valid_capsules

    def _append_capsules(self, capsules: List[Dict[str, Any]]) -> None:
        if not self.config.capsules_file:
            return
        
        with open(self.config.capsules_file, "a", encoding="utf-8") as f:
            for capsule in capsules:
                f.write(json.dumps(capsule, ensure_ascii=False) + "\n")
