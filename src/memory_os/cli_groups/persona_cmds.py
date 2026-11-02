import argparse
import json
from datetime import timezone
from pathlib import Path

from memory_os import MemoryOSConfig

UTC = timezone.utc
def cmd_idea(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.toolkit.prompt_registry import PromptRegistry, idea_expand_dry_run

    registry = PromptRegistry(config)
    rendered = idea_expand_dry_run(registry, args.text)
    if args.format == "json":
        print(json.dumps({"text": args.text, "rendered_prompt": rendered}, indent=2))
    else:
        print(rendered)
        print("\n(rendered only — no LLM call was made; pass this prompt to a provider yourself)")
    return 0

def cmd_persona_sync(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.persona import PersonaManager
    pm = PersonaManager(config.persona_memory_dir)
    transcript_path = Path(args.log_file).resolve()
    
    print(f"Extracting persona from {transcript_path.name}...")
    success = pm.sync_from_transcript(transcript_path, args.provider, args.model)
    if success:
        print(f"Persona successfully synced to {config.persona_memory_dir / 'persona.yaml'}")
        return 0
    else:
        print("Failed to sync persona.")
        return 1

def cmd_persona(args: argparse.Namespace, config: MemoryOSConfig) -> int:
    from memory_os.modules.persona import PersonaManager
    pm = PersonaManager(config.persona_memory_dir)
    print(pm.get_persona())
    return 0
