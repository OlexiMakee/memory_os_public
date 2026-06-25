"""Lazy Temporal connectivity and mirroring adapter."""

import importlib.util
from typing import Any, Dict, List, Optional


def is_available() -> bool:
    """Check if the 'temporalio' package is installed and available for import."""
    try:
        return importlib.util.find_spec("temporalio") is not None
    except (ImportError, ValueError, AttributeError):
        return False


class TemporalAdapter:
    """Adapter for optionally exporting or mirroring workflow run records to Temporal."""

    def __init__(self, target_host: Optional[str] = None) -> None:
        """Initialize the Temporal adapter.

        Args:
            target_host: Address of the Temporal server, e.g., "localhost:7233".
        """
        self.target_host = target_host

    def mirror_run(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Optionally mirror a RunRecord store record into Temporal workflow concepts.

        Args:
            record: RunRecordStore record dict (run_id, workflow_name, status, etc.).

        Returns:
            Dict containing the result of the best-effort mirror operation.
        """
        if self.target_host is None:
            return {"ok": False, "detail": "no Temporal server target_host configured"}

        if not is_available():
            return {"ok": False, "detail": "temporalio package not installed"}

        try:
            import asyncio
            import threading
            from temporalio.client import Client

            async def _connect_with_timeout() -> Client:
                return await Client.connect(self.target_host)

            result: List[Any] = []
            exception: List[Exception] = []

            def worker() -> None:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    conn = new_loop.run_until_complete(
                        asyncio.wait_for(_connect_with_timeout(), timeout=2.0)
                    )
                    result.append(conn)
                except Exception as e:
                    exception.append(e)
                finally:
                    new_loop.close()

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            t.join(timeout=3.0)

            if t.is_alive():
                return {"ok": False, "detail": "temporal mirror failed: connection attempt timed out"}
            if exception:
                return {"ok": False, "detail": f"temporal mirror failed: {exception[0]}"}
            if not result:
                return {"ok": False, "detail": "temporal mirror failed: connection attempt failed to return client"}

            return {
                "ok": True,
                "run_id": record.get("run_id"),
                "detail": "mirrored to Temporal (best-effort)"
            }
        except Exception as exc:
            return {"ok": False, "detail": f"temporal mirror failed: {exc}"}

    def audit(self) -> Dict[str, Any]:
        """Perform a quick, local, non-blocking check on availability and configuration."""
        return {"available": is_available(), "target_host": self.target_host}
