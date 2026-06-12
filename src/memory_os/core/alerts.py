import logging
import subprocess
from pathlib import Path
from typing import Optional
from memory_os.core.config import MemoryOSConfig

logger = logging.getLogger(__name__)

class AlertManager:
    def __init__(self, config: MemoryOSConfig):
        self.config = config
        self.data_dir = config.root_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_log = self.data_dir / "alerts.log"
        
    def send_alert(self, title: str, message: str, is_critical: bool = False):
        """
        Send a desktop notification on macOS and log it to alerts.log.
        """
        level = "CRITICAL" if is_critical else "WARNING"
        log_entry = f"[{level}] {title}: {message}\n"
        
        # Write to log
        try:
            with open(self.alerts_log, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as e:
            logger.error(f"Failed to write to alerts.log: {e}")
            
        # Desktop notifications via osascript disabled as per user instruction.
        pass

