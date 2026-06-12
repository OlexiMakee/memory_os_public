from dataclasses import dataclass

@dataclass
class RuntimeDecision:
    provider: str
    model: str
    reason: str

class LLMRouter:
    """Routes tasks to the most appropriate LLM provider and model based on task type."""
    
    def route(self, task_type: str, input_size_tokens: int = 0) -> RuntimeDecision:
        if task_type in {
            "memory_compaction",
            "jsonl_extraction",
            "tagging",
            "classification",
            "short_rewrite",
        }:
            return RuntimeDecision(
                provider="ollama",
                model="gemma4:4b",
                reason="cheap local small-model task"
            )
        if task_type in {
            "fast_mac_inference",
            "local_chat",
        }:
            return RuntimeDecision(
                provider="mlx",
                model="mlx-community/gemma-3-4b-it-4bit",
                reason="Apple Silicon optimized local inference"
            )
        if task_type in {
            "batch_generation",
            "multi_user_serving",
            "heavy_parallel",
        }:
            return RuntimeDecision(
                provider="desktop_vllm",
                model="Qwen/Qwen2.5-7B-Instruct",
                reason="GPU server batch inference"
            )
        if task_type in {
            "agentic_reasoning",
            "deep_architecture",
            "high_stakes_analysis",
        }:
            return RuntimeDecision(
                provider="cloud",
                model="gpt-5.5-thinking",
                reason="requires stronger reasoning"
            )
            
        return RuntimeDecision(
            provider="ollama",
            model="gemma4:4b",
            reason="default local fallback"
        )
