"""
Lightweight performance benchmarking module for agent decisions.
Tracks LLM call execution time, token usage, and success/failure status.
No external dependencies - uses only stdlib time and json modules.
"""

import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List


class PerformanceBenchmark:
    """
    Tracks performance metrics for agent decisions.
    
    In-memory accumulation during runtime, exported to JSON on shutdown.
    Uses time.perf_counter() for sub-millisecond accuracy + datetime for readability.
    """
    
    def __init__(self, agent_id: str):
        """
        Initialize benchmarking for an agent.
        
        Args:
            agent_id: Identifier for the agent (used in JSON export)
        """
        self.agent_id = agent_id
        self.start_time = datetime.now().isoformat()
        self.runtime_start = time.perf_counter()
        self.decisions: List[Dict[str, Any]] = []
        self._current_timer: Optional[float] = None
        self._current_decision: Dict[str, Any] = {}
    
    def start_timer(self) -> None:
        """Start a timing measurement for a decision."""
        self._current_timer = time.perf_counter()
        self._current_decision = {}
    
    def end_timer(self) -> float:
        """
        End the current timing measurement.
        
        Returns:
            Execution time in milliseconds (rounded to 2 decimals)
        """
        if self._current_timer is None:
            raise RuntimeError("Timer was not started. Call start_timer() first.")
        
        elapsed_ms = (time.perf_counter() - self._current_timer) * 1000
        self._current_decision["execution_ms"] = round(elapsed_ms, 2)
        return elapsed_ms
    
    def record_decision(
        self,
        tokens_used: int = 0,
        status: str = "success",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record a completed decision with metadata.
        
        Args:
            tokens_used: Number of tokens consumed by LLM call (default 0)
            status: Status of decision - "success", "failure", "timeout", etc.
            metadata: Optional dict with additional info (intersection_id, decision_type, etc.)
        
        Raises:
            RuntimeError: If end_timer() was not called first
        """
        if "execution_ms" not in self._current_decision:
            raise RuntimeError(
                "Timing not recorded. Call end_timer() before record_decision()."
            )
        
        decision_entry = {
            "timestamp": datetime.now().isoformat(),
            "execution_ms": self._current_decision["execution_ms"],
            "tokens_used": tokens_used,
            "status": status,
        }
        
        if metadata:
            decision_entry["metadata"] = metadata
        
        self.decisions.append(decision_entry)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Calculate aggregate statistics from all recorded decisions.
        
        Returns:
            Dict with: total_decisions, avg_execution_ms, total_tokens, success_count, failure_count
        """
        if not self.decisions:
            return {
                "total_decisions": 0,
                "avg_execution_ms": 0,
                "total_tokens": 0,
                "success_count": 0,
                "failure_count": 0,
            }
        
        total_decisions = len(self.decisions)
        total_ms = sum(d["execution_ms"] for d in self.decisions)
        total_tokens = sum(d.get("tokens_used", 0) for d in self.decisions)
        success_count = sum(1 for d in self.decisions if d["status"] == "success")
        failure_count = total_decisions - success_count
        
        return {
            "total_decisions": total_decisions,
            "avg_execution_ms": round(total_ms / total_decisions, 2),
            "total_tokens": total_tokens,
            "success_count": success_count,
            "failure_count": failure_count,
        }
    
    def export_json(self, file_path: str) -> None:
        """
        Export all benchmarking data to a JSON file.
        
        Args:
            file_path: Absolute path where JSON will be saved
        
        File structure:
        {
            "metadata": {
                "agent_id": "...",
                "start_time": "2026-05-05T...",
                "end_time": "2026-05-05T...",
                "total_runtime_seconds": 12.34,
                "stats": { ... }
            },
            "decisions": [ ... ]
        }
        """
        end_time = datetime.now().isoformat()
        runtime_seconds = round(time.perf_counter() - self.runtime_start, 2)
        
        export_data = {
            "metadata": {
                "agent_id": self.agent_id,
                "start_time": self.start_time,
                "end_time": end_time,
                "total_runtime_seconds": runtime_seconds,
                "stats": self.get_stats(),
            },
            "decisions": self.decisions,
        }
        
        with open(file_path, "w") as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✅ [{self.agent_id}] Performance metrics exported to {file_path}")
