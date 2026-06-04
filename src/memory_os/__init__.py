"""
Memory OS — Portable Agent Memory Kernel
No Flask dependency. Stdlib only (+ optional lazy LLM adapter).
"""
from memory_os.core.core import MemoryOS
from memory_os.core.telemetry import TelemetryRecorder
from memory_os.modules.versioner import PromptVersioner
from memory_os.modules.context import ContextRegistry
from memory_os.modules.optimizer import RouteOptimizer
from memory_os.core.toml_parser import parse_toml, load_toml_file
from memory_os.core.prompt_formatter import (
    wrap_in_xml,
    format_user_profile,
    markdown_table_to_html,
    compress_dialog,
    strip_whitespace_noise,
)
from memory_os.core.config import MemoryOSConfig
from memory_os.modules.validator import MemoryValidator
from memory_os.modules.compactor import MemoryCompactor
from memory_os.modules.lifecycle import LifecycleManager
from memory_os.modules.search import MemorySearcher
from memory_os.core.interfaces import IMemoryOSConfig, IMemoryStorage, ILlmProviderService
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.llm_service import DefaultLlmProviderService

__all__ = [
    "MemoryOS",
    "TelemetryRecorder",
    "PromptVersioner",
    "ContextRegistry",
    "RouteOptimizer",
    "parse_toml",
    "load_toml_file",
    "wrap_in_xml",
    "format_user_profile",
    "markdown_table_to_html",
    "compress_dialog",
    "strip_whitespace_noise",
    "MemoryOSConfig",
    "MemoryValidator",
    "MemoryCompactor",
    "LifecycleManager",
    "MemorySearcher",
    "IMemoryOSConfig",
    "IMemoryStorage",
    "ILlmProviderService",
    "FileSystemMemoryStorage",
    "DefaultLlmProviderService",
]
