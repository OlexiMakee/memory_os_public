import json
import urllib.request
import argparse
from unittest.mock import MagicMock
from memory_os import MemoryOSConfig
from memory_os.toolkit.model_catalog import get_system_hardware, get_vram_gb
from memory_os.cli import cmd_models

def test_hardware_helpers(monkeypatch):
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = "8192\n"
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_run)
    monkeypatch.setattr("shutil.which", lambda name: name == "nvidia-smi")
    
    assert get_vram_gb() == 8.0
    
    hw = get_system_hardware()
    assert hw["vram_gb"] == 8.0
    assert hw["cpu_cores"] is not None

def test_hardware_helpers_no_gpu(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: False)
    from pathlib import Path
    monkeypatch.setattr(Path, "glob", lambda self, pattern: [])
    
    assert get_vram_gb() == 0.0

def test_cmd_models_recommend(monkeypatch, capsys):
    monkeypatch.setattr("memory_os.toolkit.model_catalog.get_system_hardware", lambda: {
        "cpu_cores": 8,
        "ram_gb": 16.0,
        "vram_gb": 8.0
    })
    
    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = json.dumps({
        "models": [
            {
                "name": "gemma3:4b",
                "size": 3338801804,
                "details": {
                    "parameter_size": "4.3B",
                    "quantization_level": "Q4_K_M"
                }
            }
        ]
    }).encode("utf-8")
    
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: mock_response)
    
    args = argparse.Namespace(models_action="recommend")
    config = MemoryOSConfig()
    
    exit_code = cmd_models(args, config)
    assert exit_code == 0
    
    captured = capsys.readouterr()
    assert "System Hardware:" in captured.out
    assert "GPU VRAM  : 8.00 GB" in captured.out
    assert "gemma3:4b" in captured.out
    assert "Yes" in captured.out
    assert "gemma3:12b" in captured.out
    assert "qwen3:8b" in captured.out
    assert "llama3:8b" in captured.out
    assert "No" in captured.out


def test_cmd_models_recommend_json(monkeypatch, capsys):
    monkeypatch.setattr("memory_os.toolkit.model_catalog.get_system_hardware", lambda: {
        "cpu_cores": 4,
        "ram_gb": 8.0,
        "vram_gb": 0.0,
    })
    monkeypatch.setattr("memory_os.toolkit.model_catalog.fetch_ollama_models", lambda host=None: [])

    exit_code = cmd_models(argparse.Namespace(models_action="recommend", format="json"), MemoryOSConfig())

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["hardware"]["cpu_cores"] == 4
    assert payload["recommendations"][0]["installed"] is False
    assert {item["status"] for item in payload["recommendations"]} <= {"fit", "tight", "no-fit"}
