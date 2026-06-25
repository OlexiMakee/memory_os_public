import os
import sys
from pathlib import Path
from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.modules.search import MemorySearcher
from memory_os.core.patch import RelationPatch

def main():
    # 1. Initialize Memory OS in a local space for this example
    config = MemoryOSConfig(Path.cwd())
    config.space = "example_agent_space"
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    searcher = MemorySearcher(config=config, repository=repo)

    print("🤖 Agent initialized.")

    # 2. Check if we already know the architecture rules
    # In Memory OS, search uses substring matching on node ID, summary, evidence, type, or tags.
    # Therefore, keyword queries work better than natural language questions unless using the vector adapter.
    query = "rule:arch_constraint"
    print(f"\n🔍 Searching memory for: '{query}'")
    results = searcher.search_memory(query)

    if not results:
        print("❌ No rules found in memory. Learning and saving a new rule...")
        # Create a patch to teach the agent a rule
        patch = RelationPatch(
            operation="upsert_node",
            source="",
            target="rule:arch_constraint",
            type="constraint",
            domain="architecture",
            confidence=1.0,
            evidence=["User initialization prompt"],
            reason="Establish project boundaries",
            payload={"summary": "We must strictly use standard Python types and avoid heavy ML frameworks for core logic."},
            created_by_protocol=0,
            required_verification_protocol=0
        )
        from memory_os.core.patch import RelationPatchStore
        store = RelationPatchStore(repo)
        patch_id = store.propose(patch)
        store.apply(patch_id)
        print("✅ Rule saved to Memory OS graph.")
        results = searcher.search_memory(query)
    else:
        print("✅ Found existing rules in memory!")

    # Format context for the LLM
    context_text = "\n".join([f"- {n.get('summary', '')}" for n in results[:3]])
    print(f"\n🧠 Context retrieved from memory:\n{context_text}\n")

    # 3. Use an LLM with the context
    user_prompt = "I need to write a module that parses data. Should I use pandas or plain dictionaries?"
    
    # We use litellm directly to show how it's done (it's what LiteLLMAdapter uses under the hood)
    system_prompt = f"You are a helpful assistant. Follow these project rules:\n{context_text}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    print(f"👤 User: {user_prompt}")
    
    if os.getenv("OPENAI_API_KEY"):
        try:
            import litellm
            print("🤖 Thinking (calling LLM via litellm)...")
            response = litellm.completion(model="gpt-4o-mini", messages=messages)
            print(f"\n🤖 Agent: {response.choices[0].message.content}")
        except ImportError:
            print("\n⚠️  litellm package not installed. Run 'pip install litellm' to use real LLM.")
            print("🤖 Agent (Simulated): Based on the rules, we must strictly use standard Python types. I will use plain dictionaries instead of pandas.")
    else:
        print("\n⚠️  No OPENAI_API_KEY found. Skipping real LLM call.")
        print("🤖 Agent (Simulated): Based on the rules, we must strictly use standard Python types. I will use plain dictionaries instead of pandas.")

    print("\n🏁 Done! To view the memory graph, run: python3 -m memory_os ui")

if __name__ == "__main__":
    main()
