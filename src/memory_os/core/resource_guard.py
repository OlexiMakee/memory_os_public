"""
ResourceGuard — cross-platform system load monitor.

Checks CPU %, RAM %, and CPU temperature (where available) before
running expensive inference stages so the host machine stays cool.

Platform notes:
  macOS M-series : psutil.sensors_temperatures() returns {}, so only
                   CPU % and RAM % are used as proxies for thermal load.
  Linux          : coretemp / k10temp / cpu_thermal sensors available.
  Windows        : limited sensor access; CPU % + RAM % only by default.
"""

from __future__ import annotations

import math
import time
from typing import Optional

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


class LoadSnapshot:
    def __init__(self, cpu: float, ram: float, temp: Optional[float]):
        self.cpu  = cpu
        self.ram  = ram
        self.temp = temp

    @property
    def level(self) -> str:
        """'cool' | 'warm' | 'hot' — human-readable heat level."""
        hot_cpu  = self.cpu  > 80
        hot_ram  = self.ram  > 88
        hot_temp = self.temp is not None and self.temp > 82
        if hot_cpu or hot_ram or hot_temp:
            return "hot"
        warn_cpu  = self.cpu  > 60
        warn_ram  = self.ram  > 75
        warn_temp = self.temp is not None and self.temp > 70
        if warn_cpu or warn_ram or warn_temp:
            return "warm"
        return "cool"

    def to_dict(self) -> dict:
        return {"cpu": round(self.cpu, 1), "ram": round(self.ram, 1),
                "temp": round(self.temp, 1) if self.temp is not None else None,
                "level": self.level}


class ResourceGuard:
    """
    Usage:
        guard = ResourceGuard(max_cpu=75, max_ram=85)
        if not guard.is_safe():
            guard.wait_until_safe()
        # ... run inference ...
    """

    def __init__(
        self,
        max_cpu:  float = 75.0,   # % — above this, inference is paused
        max_ram:  float = 85.0,   # %
        max_temp: float = 80.0,   # °C — used only when sensor is available
    ):
        self.max_cpu  = max_cpu
        self.max_ram  = max_ram
        self.max_temp = max_temp

    # ------------------------------------------------------------------
    def snapshot(self) -> LoadSnapshot:
        if not _PSUTIL:
            return LoadSnapshot(cpu=0.0, ram=0.0, temp=None)
        cpu  = psutil.cpu_percent(interval=0.3)
        ram  = psutil.virtual_memory().percent
        temp = self._read_temp()
        return LoadSnapshot(cpu=cpu, ram=ram, temp=temp)

    def is_safe(self) -> bool:
        s = self.snapshot()
        if s.cpu > self.max_cpu:
            return False
        if s.ram > self.max_ram:
            return False
        if s.temp is not None and s.temp > self.max_temp:
            return False
        return True

    def wait_until_safe(self, check_interval: float = 5.0, timeout: float = 120.0) -> bool:
        """
        Block until system load drops below thresholds.
        Returns True when safe, False if timeout was reached.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_safe():
                return True
            time.sleep(check_interval)
        return False

    # ------------------------------------------------------------------
    def _read_temp(self) -> Optional[float]:
        if not _PSUTIL:
            return None
        try:
            sensors = psutil.sensors_temperatures()
            if not sensors:
                return None
            # Try common sensor names across platforms
            for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
                entries = sensors.get(key, [])
                if entries:
                    return max(e.current for e in entries)
            # Fallback: first available sensor
            for entries in sensors.values():
                if entries:
                    return max(e.current for e in entries)
        except Exception:
            pass
        return None
