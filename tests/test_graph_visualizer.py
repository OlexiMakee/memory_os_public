import json
from pathlib import Path
import pytest

from memory_os.core.config import MemoryOSConfig
from memory_os.core.models import MemoryNode, MemoryEdge
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.modules.graph_visualizer import GraphVisualizer
from memory_os.cli import build_parser
from memory_os.cli_groups.memory_cmds import cmd_graph_map


@pytest.fixture
def temp_config(tmp_path: Path) -> MemoryOSConfig:
    cfg = MemoryOSConfig(config_path=str(tmp_path / "memory_os.config.json"))
    cfg.memory_dir.mkdir(parents=True, exist_ok=True)

    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, cfg)

    node1 = MemoryNode(
        id="fact-001",
        type="fact",
        summary="Fact node summary",
        evidence=["doc1"],
        status="verified",
    )
    node2 = MemoryNode(
        id="decision-002",
        type="decision",
        summary="Decision node summary",
        evidence=["doc2"],
        status="verified",
    )
    node3 = MemoryNode(
        id="task-003",
        type="task",
        summary="Task node summary",
        evidence=[],
        status="draft",
    )
    node4 = MemoryNode(
        id="spec-004",
        type="spec",
        summary="Spec node summary",
        evidence=[],
        status="draft",
    )

    repo.upsert_node(node1)
    repo.upsert_node(node2)
    repo.upsert_node(node3)
    repo.upsert_node(node4)

    edge1 = MemoryEdge(source="fact-001", target="decision-002", type="depends_on")
    edge2 = MemoryEdge(source="decision-002", target="task-003", type="triggers")
    edge3 = MemoryEdge(source="task-003", target="spec-004", type="fixed_by")

    repo.upsert_edge_with_protocol(edge1, protocol_level=8)
    repo.upsert_edge_with_protocol(edge2, protocol_level=8)
    repo.upsert_edge_with_protocol(edge3, protocol_level=8)

    return cfg


def test_generate_html_default_path(temp_config: MemoryOSConfig) -> None:
    visualizer = GraphVisualizer(temp_config)
    output_file = visualizer.generate_html()

    assert output_file.exists()
    assert output_file == temp_config.memory_dir / "graph.html"

    content = output_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Memory OS - Visual Graph Explorer" in content
    assert "vis.Network" in content
    assert "fact-001" in content
    assert "decision-002" in content


def test_generate_html_custom_path(temp_config: MemoryOSConfig, tmp_path: Path) -> None:
    custom_path = tmp_path / "custom_output" / "my_graph.html"
    visualizer = GraphVisualizer(temp_config)
    output_file = visualizer.generate_html(output_path=custom_path)

    assert output_file.exists()
    assert output_file == custom_path

    content = output_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "vis.Network" in content


def test_node_and_edge_color_coding(temp_config: MemoryOSConfig) -> None:
    visualizer = GraphVisualizer(temp_config)
    output_file = visualizer.generate_html()
    content = output_file.read_text(encoding="utf-8")

    # Check node color values mapped in html payload
    assert "#3B82F6" in content  # fact blue
    assert "#8B5CF6" in content  # decision purple
    assert "#F59E0B" in content  # task amber
    assert "#10B981" in content  # spec green

    # Check edge relation types present
    assert "depends_on" in content
    assert "triggers" in content
    assert "fixed_by" in content


def test_cli_graph_map_visual_flag(temp_config: MemoryOSConfig, capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()
    args = parser.parse_args(["graph-map", "--visual"])

    ret = cmd_graph_map(args, temp_config)
    assert ret == 0

    captured = capsys.readouterr()
    expected_path = temp_config.memory_dir / "graph.html"
    assert f"Visual memory graph written to: {expected_path}" in captured.out
    assert expected_path.exists()


def test_cli_graph_map_html_flag(temp_config: MemoryOSConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    custom_html = tmp_path / "cli_vis.html"
    parser = build_parser()
    args = parser.parse_args(["graph-map", "--html", str(custom_html)])

    ret = cmd_graph_map(args, temp_config)
    assert ret == 0

    captured = capsys.readouterr()
    assert f"Visual memory graph written to: {custom_html}" in captured.out
    assert custom_html.exists()
