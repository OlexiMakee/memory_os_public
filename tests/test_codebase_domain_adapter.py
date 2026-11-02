import json
from pathlib import Path

from memory_os.cli import build_parser, cmd_codebase
from memory_os.core.adapters import AstDomainAdapter, CodebaseDomainAdapter, DomainAdapterIngestor, DomainAdapterRegistry, GrepDomainAdapter, IDomainAdapter
from memory_os.core.config import MemoryOSConfig
from memory_os.core.repository import MemoryRepository
from memory_os.core.safe_id import validate_safe_node_id
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.modules.validator import MemoryValidator
from memory_os.modules.context import ContextRegistry


class DummyTextAdapter(IDomainAdapter):
    def get_domain_name(self):
        return "dummy_text"

    def supports(self, resource_uri, content=None):
        return resource_uri.endswith(".txt")

    def extract_metadata(self, resource_uri, content):
        return {"dummy_marker": "seen"}

    def parse_to_patches(self, resource_uri, content, protocol_level=4):
        return []


def _config(root: Path) -> MemoryOSConfig:
    (root / "memory").mkdir()
    (root / "agent_context").mkdir()
    (root / "memory_os.config.json").write_text(
        json.dumps({"version": "0.1", "memory_dir": "memory", "db_path": "memory/memory_os.db"}),
        encoding="utf-8",
    )
    return MemoryOSConfig(config_path=str(root / "memory_os.config.json"))


def test_codebase_adapter_traverses_dependencies_and_dependents():
    adapter = CodebaseDomainAdapter()
    items_by_file = {
        "src/app.py": {"meta": {"dependencies": ["memory_os.core.config"]}},
        "src/memory_os/core/config.py": {"meta": {"dependencies": []}},
        "src/unrelated.py": {"meta": {"dependencies": []}},
    }

    dependencies = adapter.traverse_dependencies({"src/app.py"}, 1, items_by_file)
    assert dependencies == {"src/app.py", "src/memory_os/core/config.py"}

    reverse = adapter.build_reverse_dependency_map(items_by_file)
    assert reverse["src/memory_os/core/config.py"] == {"src/app.py"}

    dependents = adapter.traverse_dependents({"src/memory_os/core/config.py"}, 1, reverse)
    assert dependents == {"src/memory_os/core/config.py", "src/app.py"}


def test_ast_adapter_extracts_metadata_and_patches():
    adapter = AstDomainAdapter()
    source = "import os\n\nclass Example:\n    pass\n\ndef run():\n    pass\n"

    metadata = adapter.extract_metadata("src/example.py", source)
    patches = adapter.parse_to_patches("src/example.py", source)

    assert metadata["domain"] == "ast"
    assert metadata["classes"] == ["Example:3"]
    assert metadata["functions"] == ["run:6"]
    assert metadata["dependencies"] == ["os"]
    assert any(patch.type == "file" for patch in patches)
    assert any(patch.type == "class" for patch in patches)
    assert any(patch.type == "function" for patch in patches)
    assert any(patch.type == "module" for patch in patches)


def test_grep_adapter_reports_plain_text_metadata():
    adapter = GrepDomainAdapter()

    assert adapter.supports("notes/example.txt", "alpha\nbeta\n")
    assert adapter.extract_metadata("notes/example.txt", "alpha\n\nbeta\n") == {
        "line_count": 3,
        "nonempty_lines": 2,
        "domain": "grep",
    }


def test_codebase_adapter_builds_graph_map_primitives():
    adapter = CodebaseDomainAdapter()
    items = [
        {"meta": {"file": "src/app.py", "dependencies": ["config"], "layer": "app", "classes": [], "functions": ["main"], "routes": []}},
        {"meta": {"file": "src/config.py", "dependencies": [], "layer": "app", "classes": ["Config"], "functions": [], "routes": []}},
        {"meta": {"file": "tests/test_app.py", "dependencies": ["app"], "layer": "tests", "classes": [], "functions": ["test_main"], "routes": []}},
    ]

    forward, reverse = adapter.build_dependency_graph(items)
    assert forward["src/app.py"] == {"src/config.py"}
    assert reverse["src/app.py"] == {"tests/test_app.py"}

    god_nodes = adapter.compute_god_nodes(reverse, items)
    assert god_nodes[0]["file"] in {"src/app.py", "src/config.py"}
    assert god_nodes[0]["in_degree"] == 1

    clusters = adapter.compute_clusters(items, forward)
    assert clusters[0]["name"] == "src"
    assert clusters[0]["internal_edges"] == 1


def test_domain_adapter_registry_selects_adapter_and_marks_domain():
    registry = DomainAdapterRegistry(adapters=[DummyTextAdapter(), CodebaseDomainAdapter()])

    metadata = registry.extract_metadata("notes/example.txt", "hello")

    assert metadata == {"dummy_marker": "seen", "domain": "dummy_text"}
    assert registry.parse_to_patches("notes/example.md", "hello") == []


def test_context_registry_uses_injected_domain_registry(tmp_path):
    source = tmp_path / "example.txt"
    source.write_text("hello", encoding="utf-8")

    registry = ContextRegistry(str(tmp_path), domain_adapters=DomainAdapterRegistry([DummyTextAdapter()]))
    snapshot = registry.build_snapshot(["."], max_items=5)

    item = snapshot["items"][0]
    assert item["meta"]["file"] == "example.txt"
    assert item["meta"]["dummy_marker"] == "seen"
    assert item["meta"]["domain"] == "dummy_text"


def test_codebase_adapter_parse_to_patches_emits_safe_nodes_for_imports():
    adapter = CodebaseDomainAdapter()

    patches = adapter.parse_to_patches(
        "src/memory_os/example.py",
        "import os\nfrom memory_os.core import config\n\nclass Example:\n    pass\n\ndef run():\n    pass\n",
    )

    node_targets = [patch.target for patch in patches if patch.operation == "upsert_node"]
    assert any(target.startswith("file:") for target in node_targets)
    assert any(target.startswith("class:") for target in node_targets)
    assert any(target.startswith("function:") for target in node_targets)
    assert any(target.startswith("module:") for target in node_targets)
    for target in node_targets:
        validate_safe_node_id(target)


def test_domain_adapter_ingestor_applies_codebase_patches(tmp_path):
    config = _config(tmp_path)
    storage = FileSystemMemoryStorage()
    repo = MemoryRepository(storage, config)
    ingestor = DomainAdapterIngestor(repo)
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source_text = "import os\n\nclass App:\n    pass\n\ndef main():\n    pass\n"
    source.write_text(source_text, encoding="utf-8")

    result = ingestor.ingest_resource(
        "src/app.py",
        source_text,
        protocol_level=4,
    )

    assert result.applied is True
    assert result.patch_count >= 5
    assert len(result.patch_ids) == result.patch_count

    nodes = storage.load_jsonl(config.memory_dir / "nodes.jsonl")
    edges = storage.load_jsonl(config.memory_dir / "edges.jsonl")
    assert any(node["type"] == "file" for node in nodes)
    assert any(node["type"] == "class" for node in nodes)
    assert any(node["type"] == "function" for node in nodes)
    assert any(node["type"] == "module" for node in nodes)
    assert any(edge["type"] == "contains" for edge in edges)
    assert any(edge["type"] == "depends_on" for edge in edges)

    validator = MemoryValidator(config)
    assert validator.validate_nodes() == []
    assert validator.validate_edges() == []


def test_codebase_index_cli_indexes_python_source_tree(tmp_path, capsys):
    config = _config(tmp_path)
    source = tmp_path / "src" / "package"
    source.mkdir(parents=True)
    (source / "alpha.py").write_text("class Alpha:\n    pass\n", encoding="utf-8")
    (source / "beta.py").write_text("def beta():\n    pass\n", encoding="utf-8")
    (source / "ignored.txt").write_text("not Python", encoding="utf-8")
    args = build_parser().parse_args(["--root", str(tmp_path), "codebase", "index", "--format", "json"])

    assert cmd_codebase(args, config) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["files_indexed"] == 2
    assert report["operations_applied"] >= 4
    assert report["storage_patches_applied"] == 2
    nodes = FileSystemMemoryStorage().load_jsonl(config.memory_dir / "nodes.jsonl")
    assert {node["type"] for node in nodes} >= {"file", "class", "function"}
    assert all(node.get("evidence") != ["src/package/ignored.txt"] for node in nodes)
    patches = FileSystemMemoryStorage().load_jsonl(config.memory_dir / "patches.jsonl")
    assert len({patch["id"] for patch in patches}) == 2

    node_count = len(nodes)
    edge_count = len(FileSystemMemoryStorage().load_jsonl(config.memory_dir / "edges.jsonl"))
    assert cmd_codebase(args, config) == 0
    capsys.readouterr()
    assert len(FileSystemMemoryStorage().load_jsonl(config.memory_dir / "nodes.jsonl")) == node_count
    assert len(FileSystemMemoryStorage().load_jsonl(config.memory_dir / "edges.jsonl")) == edge_count


def test_codebase_index_cli_dry_run_does_not_mutate_graph(tmp_path, capsys):
    config = _config(tmp_path)
    source = tmp_path / "src"
    source.mkdir()
    (source / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    args = build_parser().parse_args(
        ["--root", str(tmp_path), "codebase", "index", "--dry-run", "--format", "json"]
    )

    assert cmd_codebase(args, config) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["files_indexed"] == 1
    assert report["operations_planned"] >= 3
    assert report["operations_applied"] == 0
    assert report["storage_patches_applied"] == 0
    assert FileSystemMemoryStorage().load_jsonl(config.memory_dir / "nodes.jsonl") == []
