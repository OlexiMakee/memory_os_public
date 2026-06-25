class MemoryOSError(Exception):
    """Base exception for all Memory OS errors."""
    pass

class ConfigNotFoundError(MemoryOSError):
    """Raised when the Memory OS config file cannot be found or is invalid."""
    pass

class StorageError(MemoryOSError):
    """Raised when there is an issue reading from or writing to storage."""
    pass

class ValidationError(MemoryOSError):
    """Raised when a task capsule, node, or edge fails schema validation."""
    pass

class GraphIntegrityError(MemoryOSError):
    """Raised when graph invariants are violated (e.g., missing related nodes)."""
    pass

class TelemetryBudgetExceeded(MemoryOSError):
    """Raised when telemetry is disabled or a hard cap blocks further writes."""
    pass
