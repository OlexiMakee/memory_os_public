import hashlib
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from memory_os.core.config import MemoryOSConfig

class PromptRegistry:
    """Registry for managing and rendering Memory OS prompt templates."""

    def __init__(self, config: MemoryOSConfig):
        self.config = config
        # Read prompts relative to this file's directory
        self.prompts_dir = Path(__file__).resolve().parent / "prompts"

    def _parse_file(self, file_path: Path) -> tuple[Dict[str, Any], str, str]:
        """Reads file, computes SHA-256 hash, and splits into frontmatter and body."""
        content = file_path.read_text(encoding="utf-8")
        
        # Calculate SHA-256 hash of the whole content (first 16 hex chars)
        sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        
        # Split frontmatter and body
        match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", content, re.DOTALL)
        if not match:
            # Fallback if frontmatter syntax is missing
            return {}, content, sha256
            
        yaml_text = match.group(1)
        body_text = match.group(2)
        
        metadata = {}
        for line in yaml_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            
            # Handle list parsing like [a, b, c]
            if val.startswith("[") and val.endswith("]"):
                items = []
                for item in val[1:-1].split(","):
                    item_cleaned = item.strip().strip("'\"")
                    if item_cleaned:
                        items.append(item_cleaned)
                metadata[key] = items
            else:
                val_cleaned = val.strip("'\"")
                if val_cleaned.isdigit():
                    metadata[key] = int(val_cleaned)
                else:
                    metadata[key] = val_cleaned
                    
        return metadata, body_text, sha256

    def list_prompts(self) -> List[Dict[str, Any]]:
        """List all prompt files with their parsed frontmatter and SHA-256 hashes."""
        results = []
        if not self.prompts_dir.exists():
            return results
            
        for file_path in sorted(self.prompts_dir.glob("*.md")):
            try:
                metadata, _, sha256 = self._parse_file(file_path)
                prompt_id = metadata.get("id", file_path.stem)
                version = metadata.get("version", 1)
                owner = metadata.get("owner", "unknown")
                purpose = metadata.get("purpose", "")
                
                results.append({
                    "id": prompt_id,
                    "version": version,
                    "owner": owner,
                    "purpose": purpose,
                    "sha256": sha256,
                    "path": str(file_path)
                })
            except Exception:
                # If a file is corrupt, skip or handle gracefully in listing
                pass
        return results

    def show(self, prompt_id: str) -> Dict[str, Any]:
        """Show full metadata and body for a prompt by ID."""
        if not self.prompts_dir.exists():
            raise FileNotFoundError(f"Prompts directory not found at {self.prompts_dir}")
            
        for file_path in self.prompts_dir.glob("*.md"):
            try:
                metadata, body_text, sha256 = self._parse_file(file_path)
                if metadata.get("id") == prompt_id:
                    result = dict(metadata)
                    result["body"] = body_text
                    result["sha256"] = sha256
                    result["path"] = str(file_path)
                    return result
            except Exception:
                pass
                
        raise FileNotFoundError(f"Prompt with ID '{prompt_id}' not found.")

    def render(self, prompt_id: str, input_values: Dict[str, str]) -> str:
        """Render prompt body with placeholder replacements."""
        prompt_data = self.show(prompt_id)
        body = prompt_data.get("body", "")
        
        def replacer(match):
            var_name = match.group(1)
            return input_values.get(var_name, match.group(0))
            
        return re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", replacer, body)

    def verify(self) -> Dict[str, Any]:
        """Verify all prompts conform to the strict schema requirements."""
        ok = True
        errors = []
        required_fields = ["id", "version", "owner", "purpose", "inputs", "outputs", "forbidden", "verification"]
        
        if not self.prompts_dir.exists():
            return {"ok": False, "errors": [f"Prompts directory {self.prompts_dir} does not exist."]}
            
        for file_path in sorted(self.prompts_dir.glob("*.md")):
            try:
                metadata, _, _ = self._parse_file(file_path)
                stem = file_path.stem
                
                # Check required fields
                for field in required_fields:
                    if field not in metadata:
                        ok = False
                        errors.append(f"Prompt '{file_path.name}' is missing required field: '{field}'")
                        
                # Check ID matches filename stem
                if metadata.get("id") != stem:
                    ok = False
                    errors.append(f"Prompt '{file_path.name}' ID '{metadata.get('id')}' does not match filename stem '{stem}'")
            except Exception as e:
                ok = False
                errors.append(f"Error parsing prompt '{file_path.name}': {str(e)}")
                
        return {"ok": ok, "errors": errors}

def idea_expand_dry_run(registry: PromptRegistry, raw_idea: str) -> str:
    """Dry run prompt rendering for the idea_expand prompt."""
    return registry.render("idea_expand", {"raw_idea": raw_idea})
