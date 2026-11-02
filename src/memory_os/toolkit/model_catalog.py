"""Static catalog, hardware discovery, and local-model fit recommendations."""

import json
import os
import re
import shutil
import subprocess
import urllib.request
from typing import List, Dict, Any, Optional

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

MODELS_CATALOG: List[Dict[str, Any]] = [
    {
        "name": "llama3:8b",
        "parameter_size": "8B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 6.5,
        "description": "Meta Llama 3 (8B, Q4_K_M) - Great all-rounder"
    },
    {
        "name": "llama3.1:8b",
        "parameter_size": "8B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 6.5,
        "description": "Meta Llama 3.1 (8B, Q4_K_M) - Upgraded 128k context"
    },
    {
        "name": "llama3:70b",
        "parameter_size": "70B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 64.0,
        "min_vram_gb": 48.0,
        "description": "Meta Llama 3 (70B, Q4_K_M) - Large high-reasoning model"
    },
    {
        "name": "qwen2.5:0.5b",
        "parameter_size": "0.5B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 2.0,
        "min_vram_gb": 1.0,
        "description": "Qwen 2.5 (0.5B, Q4_K_M) - Ultra-lightweight"
    },
    {
        "name": "qwen2.5:1.5b",
        "parameter_size": "1.5B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 4.0,
        "min_vram_gb": 2.0,
        "description": "Qwen 2.5 (1.5B, Q4_K_M) - Very lightweight"
    },
    {
        "name": "qwen2.5:3b",
        "parameter_size": "3B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 6.0,
        "min_vram_gb": 3.5,
        "description": "Qwen 2.5 (3B, Q4_K_M) - Great balance of speed/quality"
    },
    {
        "name": "qwen2.5:7b",
        "parameter_size": "7B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 6.0,
        "description": "Qwen 2.5 (7B, Q4_K_M) - Excellent coding/reasoning model"
    },
    {
        "name": "qwen2.5:14b",
        "parameter_size": "14B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 24.0,
        "min_vram_gb": 12.0,
        "description": "Qwen 2.5 (14B, Q4_K_M) - High quality reasoning"
    },
    {
        "name": "qwen2.5:32b",
        "parameter_size": "32B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 48.0,
        "min_vram_gb": 26.0,
        "description": "Qwen 2.5 (32B, Q4_K_M) - Advanced reasoning"
    },
    {
        "name": "phi3:3.8b",
        "parameter_size": "3.8B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 8.0,
        "min_vram_gb": 4.0,
        "description": "Microsoft Phi-3 (3.8B, Q4_K_M) - Lightweight and fast"
    },
    {
        "name": "gemma2:2b",
        "parameter_size": "2B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 6.0,
        "min_vram_gb": 3.0,
        "description": "Google Gemma 2 (2B, Q4_K_M) - Fast and capable"
    },
    {
        "name": "gemma2:9b",
        "parameter_size": "9B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 16.0,
        "min_vram_gb": 8.0,
        "description": "Google Gemma 2 (9B, Q4_K_M) - Very high quality"
    },
    {
        "name": "gemma2:27b",
        "parameter_size": "27B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 40.0,
        "min_vram_gb": 22.0,
        "description": "Google Gemma 2 (27B, Q4_K_M) - High end local model"
    },
    {
        "name": "mistral:7b",
        "parameter_size": "7B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 6.0,
        "description": "Mistral (7B, Q4_K_M) - Classic capabler"
    },
    {
        "name": "codegemma:7b",
        "parameter_size": "7B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 6.5,
        "description": "CodeGemma (7B, Q4_K_M) - Optimized for code completion"
    },
    {
        "name": "deepseek-coder:6.7b",
        "parameter_size": "6.7B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 5.5,
        "description": "DeepSeek Coder (6.7B, Q4_K_M) - Exceptional coding assistant"
    },
    {
        "name": "gemma3:4b",
        "parameter_size": "4B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 8.0,
        "min_vram_gb": 3.5,
        "description": "Google Gemma 3 (4B, Q4_K_M) - Lightweight current-gen helper"
    },
    {
        "name": "gemma3:12b",
        "parameter_size": "12B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 20.0,
        "min_vram_gb": 9.5,
        "description": "Google Gemma 3 (12B, Q4_K_M) - Capability-balanced current-gen"
    },
    {
        "name": "gemma3:27b",
        "parameter_size": "27B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 40.0,
        "min_vram_gb": 22.0,
        "description": "Google Gemma 3 (27B, Q4_K_M) - High-end current-gen reasoning"
    },
    {
        "name": "qwen3:4b",
        "parameter_size": "4B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 8.0,
        "min_vram_gb": 3.5,
        "description": "Qwen 3 (4B, Q4_K_M) - Highly active lightweight model"
    },
    {
        "name": "qwen3:8b",
        "parameter_size": "8B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 12.0,
        "min_vram_gb": 6.5,
        "description": "Qwen 3 (8B, Q4_K_M) - Standard coding/reasoning model"
    },
    {
        "name": "qwen3:14b",
        "parameter_size": "14B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 24.0,
        "min_vram_gb": 12.0,
        "description": "Qwen 3 (14B, Q4_K_M) - Strong reasoning current-gen"
    },
    {
        "name": "qwen3:32b",
        "parameter_size": "32B",
        "quantization": "Q4_K_M",
        "min_ram_gb": 48.0,
        "min_vram_gb": 26.0,
        "description": "Qwen 3 (32B, Q4_K_M) - Advanced local reasoning model"
    }
]


def get_vram_gb() -> float:
    """Detect local VRAM in GB using nvidia-smi, rocm-smi, or system sysfs files."""
    if shutil.which("nvidia-smi"):
        try:
            res = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                val = res.stdout.strip()
                if val.isdigit():
                    return float(val) / 1024.0
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    if shutil.which("rocm-smi"):
        try:
            res = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                import re
                m = re.search(r"VRAM Total Memory\s*\(B\):\s*(\d+)", res.stdout)
                if m:
                    bytes_val = int(m.group(1))
                    return float(bytes_val) / (1024.0 ** 3)
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)

    from pathlib import Path
    try:
        for card_path in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
            if card_path.exists():
                try:
                    bytes_val = int(card_path.read_text().strip())
                    return float(bytes_val) / (1024.0 ** 3)
                except Exception as _e:
                    import sys as _sys
                    print(f'Ignored exception: {_e}', file=_sys.stderr)
    except Exception as _e:
        import sys as _sys
        print(f'Ignored exception: {_e}', file=_sys.stderr)

    return 0.0


def get_system_hardware() -> Dict[str, Any]:
    """Retrieve CPU cores, System RAM, and GPU VRAM details."""
    cpu_cores = os.cpu_count() or 1
    total_ram_gb = 8.0
    if _HAS_PSUTIL:
        try:
            total_ram_gb = psutil.virtual_memory().total / (1024.0 ** 3)
        except Exception as _e:
            import sys as _sys
            print(f'Ignored exception: {_e}', file=_sys.stderr)
    vram_gb = get_vram_gb()
    return {
        "cpu_cores": cpu_cores,
        "ram_gb": total_ram_gb,
        "vram_gb": vram_gb,
    }


def fetch_ollama_models(host: Optional[str] = None, timeout: float = 2.0) -> List[Dict[str, Any]]:
    base_url = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    try:
        request = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    models: List[Dict[str, Any]] = []
    for model in payload.get("models", []):
        details = model.get("details") or {}
        size_gb = model.get("size", 0) / (1024.0 ** 3)
        parameter_size = details.get("parameter_size", "")
        if not parameter_size and "B" in model.get("name", ""):
            match = re.search(r"(\d+(?:\.\d+)?[bB])", model.get("name", ""))
            if match:
                parameter_size = match.group(1).upper()
        quantization = details.get("quantization_level", "")
        models.append({
            "name": model.get("name"),
            "parameter_size": parameter_size or "N/A",
            "quantization": quantization or "N/A",
            "min_ram_gb": round(size_gb + 2.5, 1),
            "min_vram_gb": round(size_gb + 1.5, 1),
            "description": (
                f"Ollama installed model ({parameter_size or 'unknown size'}, "
                f"{quantization or 'unknown quant'})"
            ),
            "installed": True,
        })
    return models


def recommend_models(
    hardware: Optional[Dict[str, Any]] = None,
    ollama_host: Optional[str] = None,
) -> Dict[str, Any]:
    hardware = dict(hardware or get_system_hardware())
    ram_gb = hardware["ram_gb"]
    vram_gb = hardware["vram_gb"]

    candidates = fetch_ollama_models(ollama_host)
    seen_names = {model["name"] for model in candidates}
    for model in MODELS_CATALOG:
        if model["name"] in seen_names:
            continue
        seen_names.add(model["name"])
        candidates.append({**model, "installed": False})
    candidates.sort(key=lambda model: (not model["installed"], model["name"]))

    recommendations = []
    for candidate in candidates:
        has_gpu = vram_gb > 0.0
        if has_gpu and candidate["min_vram_gb"] <= vram_gb:
            if candidate["min_vram_gb"] + 2.0 <= vram_gb:
                status = "fit"
                reason = "Fits fully in VRAM with headroom"
                suggested_context = "8192"
            else:
                status = "tight"
                reason = "Fits in VRAM but tight"
                suggested_context = "4096"
        elif candidate["min_ram_gb"] <= ram_gb:
            status = "tight"
            reason = (
                "Exceeds VRAM; runs on CPU/RAM (slower)"
                if has_gpu
                else "Runs on CPU/RAM (no VRAM detected)"
            )
            if candidate["min_ram_gb"] + 4.0 > ram_gb:
                reason += " (tight RAM)"
                suggested_context = "2048"
            else:
                suggested_context = "4096"
        else:
            status = "no-fit"
            reason = (
                f"Requires min {candidate['min_ram_gb']:.1f}GB RAM / "
                f"{candidate['min_vram_gb']:.1f}GB VRAM"
                if has_gpu
                else f"Requires min {candidate['min_ram_gb']:.1f}GB RAM"
            )
            suggested_context = "N/A"

        recommendations.append({
            "name": candidate["name"],
            "installed": bool(candidate["installed"]),
            "parameter_size": candidate["parameter_size"],
            "quantization": candidate["quantization"],
            "min_ram_gb": candidate["min_ram_gb"],
            "min_vram_gb": candidate["min_vram_gb"],
            "status": status,
            "reason": reason,
            "suggested_context": suggested_context,
        })
    return {"hardware": hardware, "recommendations": recommendations}
