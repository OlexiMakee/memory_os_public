"""Lazy Qdrant connectivity adapter for local/in-memory checks."""

import importlib.util
from typing import Any, Dict


def is_available() -> bool:
    """Check if the 'qdrant_client' package is installed and available for import."""
    try:
        return importlib.util.find_spec("qdrant_client") is not None
    except (ImportError, ValueError, AttributeError):
        return False


class QdrantAdapter:
    """Adapter for checking connectivity and status of a local/in-memory Qdrant client."""

    def __init__(self) -> None:
        pass

    def health_check(self) -> Dict[str, Any]:
        """Verify Qdrant client construction and list collections.

        Never attempts to connect to a remote/networked Qdrant server. Only uses
        the local in-memory mode.
        """
        if not is_available():
            return {"ok": False, "detail": "qdrant_client package not installed"}

        try:
            from qdrant_client import QdrantClient
            # Construct a local in-memory client to prevent network access
            client = QdrantClient(location=":memory:")
            collections_response = client.get_collections()

            # Robust extraction of the collections list/count across API versions
            if hasattr(collections_response, "collections"):
                collections = collections_response.collections
            elif isinstance(collections_response, dict):
                collections = collections_response.get("collections", [])
            else:
                collections = collections_response

            count = len(collections)

            return {
                "ok": True,
                "mode": "in-memory",
                "collection_count": count,
            }
        except Exception as exc:
            return {
                "ok": False,
                "detail": f"qdrant health check failed: {exc}",
            }

    def audit(self) -> Dict[str, Any]:
        """Perform a quick, local, non-blocking check on availability."""
        return {"available": is_available()}
