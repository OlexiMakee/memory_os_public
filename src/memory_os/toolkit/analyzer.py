import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import time

from memory_os import MemoryOS
from memory_os.core.llm_service import DefaultLlmProviderService
from memory_os.core.config import MemoryOSConfig

ADVISOR_PROMPT = """
You are the Memory OS Performance Advisor.
Review the following local telemetry and algorithm execution metrics.
Identify bottlenecks, expensive queries, or suggest architectural optimizations.
You must output exactly 1 to 3 actionable proposals in JSON format.
Each proposal must match this schema:
{
    "proposals": [
        {
            "proposal_key": "os-perf:optimization_name",
            "proposal_type": "feature",
            "priority": "high|medium|low",
            "desc": "Detailed explanation of what needs to be changed and why, based on the telemetry.",
            "recommendation": "cache_algorithm|change_model|refactor_logic"
        }
    ]
}
Return ONLY valid JSON. No markdown blocks.
"""

class OSPerformanceAnalyzer:
    """Reads SQLite telemetry and algorithm performance logs, then uses LLM to generate insights."""
    
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.memory_os = MemoryOS()
        self.llm = DefaultLlmProviderService()
        self.proposals_path = Path("agent_proposals/admin_proposals.jsonl").resolve()
        
    def _gather_digest(self) -> str:
        """Query SQLite for aggregated telemetry and performance stats."""
        conn = self.memory_os.get_connection()
        try:
            # 1. LLM Stats
            cursor = conn.cursor()
            cursor.execute("""
                SELECT model_id, COUNT(*) as calls, 
                       AVG(latency_ms) as avg_latency_ms,
                       AVG(input_tokens) as avg_in, 
                       AVG(output_tokens) as avg_out,
                       SUM(cost) as total_cost
                FROM memory_os_telemetry
                GROUP BY model_id
                ORDER BY total_cost DESC
                LIMIT 10
            """)
            llm_stats = [dict(row) for row in cursor.fetchall()]
            
            # 2. Algorithm Stats
            cursor.execute("""
                SELECT algorithm_name, COUNT(*) as runs, 
                       AVG(duration_ms) as avg_duration_ms,
                       MAX(duration_ms) as max_duration_ms
                FROM memory_os_performance
                GROUP BY algorithm_name
                ORDER BY avg_duration_ms DESC
                LIMIT 10
            """)
            algo_stats = [dict(row) for row in cursor.fetchall()]
            
            digest = ["--- LLM TELEMETRY ---"]
            if not llm_stats:
                digest.append("No LLM telemetry recorded yet.")
            for s in llm_stats:
                digest.append(f"Model: {s['model_id']} | Calls: {s['calls']} | Avg Latency: {s['avg_latency_ms']:.0f}ms | Avg Tokens (in/out): {s['avg_in']:.0f}/{s['avg_out']:.0f} | Total Cost: ${s['total_cost']:.4f}")
                
            digest.append("\n--- INTERNAL ALGORITHMS ---")
            if not algo_stats:
                digest.append("No algorithm performance recorded yet.")
            for s in algo_stats:
                digest.append(f"Algo: {s['algorithm_name']} | Runs: {s['runs']} | Avg Duration: {s['avg_duration_ms']:.0f}ms | Max Duration: {s['max_duration_ms']}ms")
                
            return "\n".join(digest)
        finally:
            conn.close()

    def generate_insights(self) -> Dict[str, Any]:
        """Gather digest, query LLM, and save proposals."""
        digest = self._gather_digest()
        
        # If no data, return early
        if "No LLM telemetry" in digest and "No algorithm performance" in digest:
            return {"status": "skipped", "reason": "No telemetry data found"}
            
        try:
            raw_response = self.llm.call_llm(
                user_message=f"Local Digest Data:\n{digest}",
                system_prompt=ADVISOR_PROMPT,
                provider="gemini",  # Fast and reliable
                model=""
            )
            
            # Clean JSON
            if raw_response.startswith("```json"):
                raw_response = raw_response[7:-3].strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response[3:-3].strip()
                
            result = json.loads(raw_response)
            proposals = result.get("proposals", [])
            
            # Save to admin proposals
            self.proposals_path.parent.mkdir(parents=True, exist_ok=True)
            created_count = 0
            
            # Avoid duplicates by checking existing keys
            existing_keys = set()
            if self.proposals_path.exists():
                with open(self.proposals_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            row = json.loads(line)
                            if "proposal_key" in row:
                                existing_keys.add(row["proposal_key"])
                        except json.JSONDecodeError:
                            pass
                            
            with open(self.proposals_path, "a", encoding="utf-8") as f:
                for p in proposals:
                    # Append timestamp to key if it lacks uniqueness, or just use as is
                    pkey = p.get("proposal_key", f"os-perf:auto_{int(time.time())}")
                    
                    if pkey in existing_keys:
                        continue
                        
                    row = {
                        "id": pkey,
                        "ts": int(time.time() * 1000),
                        "role": "system",
                        "type": p.get("proposal_type", "feature"),
                        "status": "draft",  # Crucial: waiting for developer approval
                        "priority": p.get("priority", "medium"),
                        "el": f"os-perf:recommendation:{p.get('recommendation', 'general')}",
                        "src": "memory_os.toolkit.analyzer",
                        "desc": p.get("desc", ""),
                        "proposal_key": pkey
                    }
                    f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    created_count += 1
                    existing_keys.add(pkey)
                    
            return {
                "status": "success",
                "digest": digest,
                "created_proposals": created_count,
                "proposals": proposals
            }
            
        except Exception as e:
            return {"status": "error", "reason": str(e)}
