import json
from pathlib import Path

from memory_os.core.config import MemoryOSConfig
from memory_os.linux_inventory import (
    LinuxFact,
    LinuxInventory,
    parse_key_value_lines,
    parse_table,
    query_inventory,
    sync_inventory_to_memory,
)


def make_config(tmp_path: Path) -> MemoryOSConfig:
    (tmp_path / "memory").mkdir()
    (tmp_path / "agent_context").mkdir()
    (tmp_path / "memory" / "nodes.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "edges.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "agent_context" / "task_capsules.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "memory_os.config.json").write_text(
        json.dumps(
            {
                "memory_dir": "memory",
                "capsules_file": "agent_context/task_capsules.jsonl",
                "db_path": "memory/memory_os.db",
            }
        ),
        encoding="utf-8",
    )
    return MemoryOSConfig(str(tmp_path / "memory_os.config.json"))


def test_parse_key_value_lines():
    parsed = parse_key_value_lines("Model name: AMD Ryzen\nCPU(s): 24\n")
    assert parsed["Model name"] == "AMD Ryzen"
    assert parsed["CPU(s)"] == "24"


def test_parse_df_table_with_mounted_on_header():
    rows = parse_table(
        "Filesystem Type Size Used Avail Use% Mounted on\n"
        "/dev/root ext4 10G 1G 9G 10% /\n"
    )
    assert rows == [
        {
            "Filesystem": "/dev/root",
            "Type": "ext4",
            "Size": "10G",
            "Used": "1G",
            "Avail": "9G",
            "Use%": "10%",
            "Mounted on": "/",
        }
    ]


def test_sync_inventory_replaces_linux_inventory_domain(tmp_path):
    config = make_config(tmp_path)
    first = LinuxInventory(
        generated_at="2026-01-01T00:00:00Z",
        host_id="host:test",
        facts=[
            LinuxFact("host:test", "host", "test host"),
            LinuxFact("pkg:apt:old", "package", "old package", related=["host:test"]),
        ],
    )
    second = LinuxInventory(
        generated_at="2026-01-01T00:01:00Z",
        host_id="host:test",
        facts=[
            LinuxFact("host:test", "host", "test host"),
            LinuxFact("pkg:apt:new", "package", "new package", related=["host:test"]),
        ],
    )

    sync_inventory_to_memory(config, first)
    sync_inventory_to_memory(config, second)

    assert query_inventory(config, "new package")
    assert not query_inventory(config, "old package")


def test_sync_inventory_removes_stale_unscoped_inventory_edges(tmp_path):
    config = make_config(tmp_path)
    first = LinuxInventory(
        generated_at="2026-01-01T00:00:00Z",
        host_id="host:test",
        facts=[
            LinuxFact("host:test", "host", "test host"),
            LinuxFact("port:127.0.0.1:1111", "port", "old port", related=["host:test"]),
        ],
    )
    second = LinuxInventory(
        generated_at="2026-01-01T00:01:00Z",
        host_id="host:test",
        facts=[
            LinuxFact("host:test", "host", "test host"),
            LinuxFact("port:127.0.0.1:2222", "port", "new port", related=["host:test"]),
        ],
    )

    sync_inventory_to_memory(config, first)
    edges_path = tmp_path / "memory" / "edges.jsonl"
    with edges_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "source": "port:127.0.0.1:1111",
            "target": "repo:external",
            "type": "co_tagged",
            "domain": "",
        }) + "\n")

    sync_inventory_to_memory(config, second)

    edges = [json.loads(line) for line in edges_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert all("port:127.0.0.1:1111" not in (edge["source"], edge["target"]) for edge in edges)


def test_sync_inventory_removes_preexisting_dangling_edges(tmp_path):
    config = make_config(tmp_path)
    inventory = LinuxInventory(
        generated_at="2026-01-01T00:00:00Z",
        host_id="host:test",
        facts=[
            LinuxFact("host:test", "host", "test host"),
            LinuxFact("port:127.0.0.1:2222", "port", "new port", related=["host:test"]),
        ],
    )
    edges_path = tmp_path / "memory" / "edges.jsonl"
    with edges_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "source": "port:127.0.0.1:1111",
            "target": "port:127.0.0.1:3333",
            "type": "co_tagged",
            "domain": "",
        }) + "\n")

    sync_inventory_to_memory(config, inventory)

    edges = [json.loads(line) for line in edges_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert all(edge["source"] != "port:127.0.0.1:1111" for edge in edges)


def test_collect_gpu_details(monkeypatch):
    from memory_os.linux_inventory import LinuxInventoryCollector
    collector = LinuxInventoryCollector()

    # Mock _run
    def fake_run(name, argv, timeout=None):
        class CP:
            def __init__(self, argv, stdout, stderr, returncode=0):
                self.argv = argv
                self.stdout = stdout
                self.stderr = stderr
                self.returncode = returncode
        if argv[0] == "lspci":
            return CP(argv, "01:00.0 VGA compatible controller: NVIDIA Corporation GA104 [GeForce RTX 3060 Ti]", "", 0)
        elif argv[0] == "nvidia-smi":
            return CP(argv, "Driver Version: 550.90   CUDA Version: 12.4", "", 0)
        elif argv[0] == "nvcc":
            return CP(argv, "nvcc: NVIDIA (R) Cuda compiler driver\nrelease 12.4, V12.4.99", "", 0)
        elif "vulkaninfo" in argv[0]:
            return CP(argv, "Vulkan Instance Version: 1.3.275", "", 0)
        return None

    monkeypatch.setattr(collector, "_run", fake_run)
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")

    facts = collector._collect_gpu()
    
    # Verify we extracted facts
    facts_dict = {f.id: f for f in facts}
    assert "gpu:nvidia:smi" in facts_dict
    assert facts_dict["gpu:nvidia:smi"].data["driver_version"] == "550.90"
    assert facts_dict["gpu:nvidia:smi"].data["cuda_version"] == "12.4"
    assert "gpu:cuda:nvcc" in facts_dict
    assert facts_dict["gpu:cuda:nvcc"].data["nvcc_version"] == "12.4"
    assert "gpu:vulkan:info" in facts_dict
    assert facts_dict["gpu:vulkan:info"].data["vulkan_active"] is True
