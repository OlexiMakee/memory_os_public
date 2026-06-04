from memory_os.core.logger import get_logger
logger = get_logger(__name__)
"""
User Persona Extractor for Memory OS.
Isolates communication style and preferences from the main architectural knowledge base.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional
import yaml
import re

from memory_os.core.interfaces import ILlmProviderService
from memory_os.core.llm_service import DefaultLlmProviderService

PERSONA_PROMPT = """
You are the Persona Extraction Engine for Memory OS.
Analyze the provided chat dialogue and extract ONLY the user's communication style,
formatting preferences, and language preferences.
DO NOT extract any technical, code, or architectural rules.
Return the result strictly as a valid JSON object matching this schema:
{
  "language": "preferred language",
  "verbosity": "e.g., concise, highly detailed",
  "formatting": "e.g., uses YAML, bullet points",
  "tone": "e.g., direct, polite",
  "custom_rules": ["rule1", "rule2"]
}
"""

class PersonaManager:
    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.persona_file = self.storage_dir / "persona.yaml"
        self.llm: ILlmProviderService = DefaultLlmProviderService()

    def sync_from_transcript(self, transcript_path: Path, provider: str = "gemini", model: str = "") -> bool:
        if not transcript_path.exists():
            return False
            
        dialogue = []
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    entry = json.loads(line)
                    # Support Antigravity transcript format
                    if entry.get("type") in ("USER_INPUT", "MODEL_RESPONSE", "PLANNER_RESPONSE") and "content" in entry:
                        role = "user" if entry["type"] == "USER_INPUT" else "assistant"
                        content = entry['content']
                        # Strip code blocks to save LLM context
                        content = re.sub(r'```.*?```', '[CODE_REMOVED]', content, flags=re.DOTALL)
                        dialogue.append(f"{role}: {content[:2000]}")
                except Exception:
                    pass
        
        if not dialogue:
            return False

        compressed = "\n".join(dialogue[-50:]) # Take last 50 turns
        
        try:
            raw_response = self.llm.call_llm(
                user_message=compressed,
                system_prompt=PERSONA_PROMPT,
                provider=provider,
                model=model
            )
            
            # Clean up markdown block if present
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:-3].strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response[3:-3].strip()
                
            result = json.loads(raw_response)
                
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            with open(self.persona_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            return True
        except Exception as e:
            logger.info(f"Error syncing persona: {e}")
            return False
            
    def get_persona(self) -> str:
        if not self.persona_file.exists():
            return "No persona recorded."
        return self.persona_file.read_text(encoding="utf-8")
