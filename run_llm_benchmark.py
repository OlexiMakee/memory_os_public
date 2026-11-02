import sys
import os
from pprint import pprint

sys.path.insert(0, os.path.abspath('src'))

from memory_os.llm import LLMGateway, LLMRouter, ChatMessage, LLMOptions, LLMRequest
from memory_os.core.core import MemoryOS

def main():
    print("--- Memory OS LLM Benchmark ---")
    
    # Initialize DB for telemetry logging
    db = MemoryOS()
    
    # Initialize Gateway
    gateway = LLMGateway()
    router = LLMRouter()
    
    # Try registering providers (we won't fail if they aren't installed, just mock or warn)
    try:
        from memory_os.llm.providers.ollama_provider import OllamaProvider
        gateway.register(OllamaProvider())
        print("[+] OllamaProvider registered")
    except ImportError:
        print("[-] OllamaProvider not available (pip install ollama)")
        
    try:
        from memory_os.llm.providers.openai_compatible_provider import OpenAICompatibleProvider
        # Mock registration for demonstration
        gateway.register(OpenAICompatibleProvider(base_url="http://localhost:8000/v1"))
        print("[+] OpenAICompatibleProvider registered")
    except ImportError:
        print("[-] OpenAICompatibleProvider not available (pip install openai)")

    if not gateway.providers:
        print("No providers available for benchmarking. Exiting.")
        return

    # Create a mock task
    task_type = "jsonl_extraction"
    decision = router.route(task_type)
    
    print(f"Routing Decision for '{task_type}':")
    print(f"  Provider: {decision.provider}")
    print(f"  Model: {decision.model}")
    print(f"  Reason: {decision.reason}")

    # For benchmark purposes, let's just construct the request and attempt it if the provider exists.
    # Otherwise, we just show the structure.
    request = LLMRequest(
        model=decision.model,
        task_type=task_type,
        messages=[
            ChatMessage(role="system", content="Extract compact memory events as JSONL."),
            ChatMessage(role="user", content="User tested Gemma 4B in Ollama UI...")
        ],
        options=LLMOptions(
            temperature=0.1,
            max_tokens=100,
            json_mode=True,
        )
    )

    if decision.provider in gateway.providers:
        print(f"\n[!] Attempting generation via {decision.provider}...")
        try:
            response = gateway.generate(decision.provider, request)
            print("\nResponse:")
            print(f"  Content: {response.content[:50]}...")
            print(f"  Latency: {response.latency_sec:.2f}s")
            print(f"  Tokens/sec: {response.tokens_per_sec}")
            
            # Log telemetry
            db.log_llm_telemetry(
                provider=response.provider,
                model=response.model,
                task_type=request.task_type,
                latency_sec=response.latency_sec,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                success=True
            )
            print("[+] Telemetry logged to SQLite")
        except Exception as e:
            print(f"[-] Generation failed: {e}")
            db.log_llm_telemetry(
                provider=decision.provider,
                model=decision.model,
                task_type=request.task_type,
                latency_sec=0.0,
                input_tokens=0,
                output_tokens=0,
                success=False
            )
    else:
        print(f"[-] The routed provider '{decision.provider}' is not registered.")

if __name__ == '__main__':
    main()
