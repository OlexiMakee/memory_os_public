#!/usr/bin/env python3
import sys
import os
import argparse
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_os import MemoryOSConfig, MemoryCompactor

def call_llm(user_message: str, provider_override: Optional[str] = None, model_override: Optional[str] = None) -> str:
    from memory_os.modules.compactor import SYSTEM_PROMPT
    from app.services.llm_clients import LLMClientFactory
    providers_to_try = [provider_override] if provider_override else ["gemini", "openrouter", "openai"]
    for provider in providers_to_try:
        api_key, base_url, model = LLMClientFactory.get_provider_config(provider, model_override)
        if api_key and base_url:
            try:
                client = LLMClientFactory.create_client(provider)
                chunks = []
                for chunk in client.stream_chat(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    user_message=user_message,
                    system_prompt=SYSTEM_PROMPT
                ):
                    chunks.append(chunk)
                return "".join(chunks)
            except Exception as exc:
                print(f"Warning: failed with provider {provider}: {exc}", file=sys.stderr)
    raise RuntimeError("No LLM provider configured with valid API keys.")

def compact_capsules(root_dir: Path, provider: Optional[str] = None, model: Optional[str] = None) -> int:
    config = MemoryOSConfig()
    config.root_dir = Path(root_dir).resolve()
    
    # Ensure memory_dir, capsules_file, snapshot_file exist relative to root_dir
    config.data["memory_dir"] = "memory"
    config.data["capsules_file"] = "agent_context/task_capsules.jsonl"
    config.data["snapshot_file"] = "agent_context/memory_snapshot.json"

    compactor = MemoryCompactor(config)
    # Monkey-patch the compactor's _call_llm to use this module's call_llm (so mocks catch it)
    compactor._call_llm = call_llm
    return compactor.compact_capsules(provider=provider, model=model)

def main() -> int:
    parser = argparse.ArgumentParser(description="Memory OS task capsules compactor.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--provider")
    parser.add_argument("--model")
    args = parser.parse_args()
    return compact_capsules(Path(args.root), args.provider, args.model)

if __name__ == "__main__":
    sys.exit(main())
