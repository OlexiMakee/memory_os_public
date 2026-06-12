import uuid
from typing import Optional, Dict, Any, List
from .core import MemoryOS

class TaskQueue:
    """SQLite-backed queue for background LLM and memory tasks."""

    def __init__(self, db: MemoryOS):
        self.db = db

    def enqueue(self, task_type: str, provider: str, model: str, input_ref: str, priority: int = 5) -> str:
        """Enqueue a new background task."""
        job_id = str(uuid.uuid4())
        conn = self.db.get_connection()
        try:
            conn.execute("""
                INSERT INTO memory_os_jobs (job_id, task_type, priority, provider, model, input_ref)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (job_id, task_type, priority, provider, model, input_ref))
            conn.commit()
            return job_id
        finally:
            conn.close()

    def dequeue(self) -> Optional[Dict[str, Any]]:
        """Fetch the highest priority queued task and mark it as processing."""
        conn = self.db.get_connection()
        try:
            # We use an immediate transaction to avoid race conditions if possible
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM memory_os_jobs 
                WHERE status = 'queued' 
                ORDER BY priority DESC, created_at ASC 
                LIMIT 1
            """)
            row = cursor.fetchone()
            
            if row:
                job = dict(row)
                cursor.execute("UPDATE memory_os_jobs SET status = 'processing' WHERE job_id = ?", (job["job_id"],))
                conn.commit()
                return job
            
            conn.commit()
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def complete(self, job_id: str, success: bool = True) -> None:
        """Mark a task as completed or failed."""
        status = 'completed' if success else 'failed'
        conn = self.db.get_connection()
        try:
            conn.execute("UPDATE memory_os_jobs SET status = ? WHERE job_id = ?", (status, job_id))
            conn.commit()
        finally:
            conn.close()
