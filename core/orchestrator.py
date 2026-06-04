from typing import List, Dict, Any
import json
from dataclasses import dataclass

@dataclass
class SubTask:
    description: str
    target_level: int
    dependencies: List[str]

class TaskOrchestrator:
    """
    Decomposes high-level (L12) tasks into smaller resource-bound subtasks (L0-L11).
    """
    def __init__(self, llm_service=None):
        """
        llm_service is injected to allow the orchestrator to query an LLM 
        to perform the decomposition if the task requires reasoning.
        """
        self.llm = llm_service

    def decompose_task(self, main_task: str, current_level: int) -> List[SubTask]:
        """
        Takes a complex task and breaks it into smaller subtasks, strictly assigning
        them to lower execution levels (e.g., L0 for SQL, L2 for AST refactoring).
        """
        if current_level < 5:
            # Low-level tasks shouldn't be decomposed further
            return [SubTask(description=main_task, target_level=current_level, dependencies=[])]

        # If we have an LLM, we can dynamically ask it to decompose the task.
        # For this MVP abstraction, if no LLM is provided, we return a mock decomposition.
        if not self.llm:
            return self._mock_decomposition(main_task, current_level)
            
        # In a real implementation, we would build a strict JSON schema prompt
        # asking the LLM to output a list of subtasks and assigning each a level < current_level
        prompt = f"Decompose this task into subtasks: {main_task}. Max level {current_level - 1}."
        # result = self.llm.execute(prompt)
        # return self._parse_llm_response(result)
        
        return self._mock_decomposition(main_task, current_level)
        
    def _mock_decomposition(self, main_task: str, current_level: int) -> List[SubTask]:
        """Fallback deterministic split for testing purposes."""
        return [
            SubTask(
                description=f"Initial audit for: {main_task[:20]}...",
                target_level=0,
                dependencies=[]
            ),
            SubTask(
                description=f"Execute core logic for: {main_task[:20]}...",
                target_level=max(1, current_level - 3),
                dependencies=["Initial audit"]
            )
        ]
