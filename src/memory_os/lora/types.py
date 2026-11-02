from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from memory_os.llm.types import ChatMessage


@dataclass
class ToolCallExample:
    """One training example: a conversation that ends in an assistant turn,
    optionally with a tool call. Source-agnostic — built from task capsules,
    local documents, or hand-written examples, then flattened to the shape
    TRL's SFTTrainer expects."""

    messages: List[ChatMessage]
    tool_call: Optional[Dict[str, Any]] = None  # {"name": ..., "arguments": {...}}
    source: str = ""  # provenance, e.g. "capsule:task_42" or "doc:DEV_STRATEGY.md"

    def to_trl_dict(self) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "messages": [{"role": m.role, "content": m.content} for m in self.messages]
        }
        if self.tool_call:
            record["messages"].append({
                "role": "assistant",
                "tool_calls": [{"type": "function", "function": self.tool_call}],
            })
        return record


@dataclass
class SkillAdapterSpec:
    """Declares what one LoRA adapter is for — not how to train it.
    Registered via AdapterRegistry once a LoraTrainingConfig has produced a
    dataset and a rendered training script for it."""

    name: str  # e.g. "memory", "terminal", "docs", "creative"
    description: str
    base_model: str  # e.g. "Qwen/Qwen3-8B"
    dataset_path: str  # JSONL of ToolCallExample.to_trl_dict() rows
    target_modules: List[str] = field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"]
    )
    rank: int = 16
    alpha: int = 32
    notes: str = ""
    # "action" = feeds an agent_brain.brain.ActionBrain (terse, JSON-only,
    # ideally a base model — see docs/encyclopedia/agent_brain.md).
    # "responder" = feeds an agent_brain.responder.Responder (natural
    # language, instruct/creative model). "creative" = a responder-role
    # adapter specifically for tone/style rather than task content.
    role: str = "action"
    # Which parameter-efficient fine-tuning method produced this adapter.
    # LoRA is the only one this module actually trains/renders today — see
    # agent_context/IMPORTANT_PROPOSAL.md §13 (Neural Capability Manager):
    # this field exists so a future second backend (DoRA, IA3, ...) is a
    # new value here, not a schema migration. No multi-backend code is
    # built until a second backend is actually being integrated.
    adapter_kind: str = "lora"
    # Which trl trainer rendered this version's training script: "sft"
    # (default, the only stage most action adapters need), "dpo" (a second
    # stage after sft, ranking chosen-vs-rejected responses), or "grpo"
    # (group-relative policy optimization against a reward function -- see
    # LoraTrainingConfig.method). Declarative bookkeeping like adapter_kind:
    # nothing reads this to change runtime behavior today.
    training_method: str = "sft"
    # The declarative manifest contract from IMPORTANT_PROPOSAL.md §13's
    # Unix-plugin framing: a skill pack should declare what it covers and
    # what it clashes with, not be a "magic file" the manager just loads.
    # None of this is enforced anywhere yet — there is no runtime that
    # loads two adapters at once to check compatible_with/incompatible_with
    # against. It is declared now because declaring it is free; enforcing
    # it is real work deferred until something actually combines adapters
    # (AdapterFusion-style or otherwise).
    capabilities: List[str] = field(default_factory=list)  # e.g. ["sql", "journalism", "uk_slang"]
    compatible_with: List[str] = field(default_factory=list)  # adapter names known to combine safely
    incompatible_with: List[str] = field(default_factory=list)  # adapter names known to conflict
