import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_os.core.config import MemoryOSConfig
from memory_os.core.storage import FileSystemMemoryStorage
from memory_os.core.repository import MemoryRepository
from memory_os.core.core import MemoryOS
from memory_os.toolkit.spec_workflow import SpecManager
from memory_os.toolkit.spec_sync import sync_specs_to_memory, DOMAIN

@pytest.fixture
def temp_root():
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

def test_spec_sync_lifecycle(temp_root):
    # Setup Config
    config_path = temp_root / "memory_os.config.json"
    config_path.write_text(json.dumps({
        "memory_dir": "memory",
        "db_path": "memory/memory_os.db",
        "snapshot_file": "agent_context/memory_snapshot.json"
    }))
    config = MemoryOSConfig(config_path=str(config_path))
    
    config.memory_dir.mkdir(parents=True, exist_ok=True)
    config.internal_memory_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize DB and repos
    MemoryOS(config)
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    
    # 1. Create a spec
    manager = SpecManager(temp_root)
    paths = manager.init_feature(
        title="Verification Test",
        description="Verify spec sync features work.",
        feature_id="002-verification"
    )
    
    # 2. Run sync
    res = sync_specs_to_memory(config)
    assert res["features"] == 1
    assert res["requirements"] == 1
    assert res["scenarios"] == 1
    assert res["tasks"] == 3
    assert res["nodes_upserted"] == 6
    assert res["edges_upserted"] == 8
    
    # Verify nodes in repo
    nodes = repo.get_nodes()
    spec_nodes = [n for n in nodes if n.domain == DOMAIN]
    assert len(spec_nodes) == 6
    
    feat_node = next(n for n in spec_nodes if n.type == "spec_feature")
    assert feat_node.id == "spec:feature:002-verification"
    assert "Verification Test" in feat_node.summary
    assert feat_node.status == "draft"
    
    req_node = next(n for n in spec_nodes if n.type == "spec_requirement")
    assert req_node.id == "spec:requirement:002-verification:FR-001"
    
    task_nodes = [n for n in spec_nodes if n.type == "spec_task"]
    assert len(task_nodes) == 3
    for t in task_nodes:
        assert t.status == "pending"
        
    # Verify edges
    edges = repo.get_edges()
    spec_edges = [e for e in edges if e.domain == DOMAIN]
    assert len(spec_edges) == 8
    
    # 3. Check task done state sync
    # Modify tasks.md to mark T001 as done
    tasks_file = paths.tasks
    content = tasks_file.read_text(encoding="utf-8")
    updated_content = content.replace("- [ ] T001", "- [x] T001")
    tasks_file.write_text(updated_content, encoding="utf-8")
    
    # Re-sync
    sync_specs_to_memory(config)
    
    # Verify status changed to done
    repo_updated = MemoryRepository(FileSystemMemoryStorage(), config)
    t001_node = next(n for n in repo_updated.get_nodes() if n.id == "spec:task:002-verification:T001")
    assert t001_node.status == "done"
    
    # 4. Check clean up of deleted features
    # Delete feature directory
    import shutil
    shutil.rmtree(paths.root)
    
    # Re-sync
    res_cleanup = sync_specs_to_memory(config)
    assert res_cleanup["features"] == 0
    assert res_cleanup["nodes_upserted"] == 0
    
    # Verify graph is empty of spec nodes and edges
    repo_cleaned = MemoryRepository(FileSystemMemoryStorage(), config)
    assert len([n for n in repo_cleaned.get_nodes() if n.domain == DOMAIN]) == 0
    assert len([e for e in repo_cleaned.get_edges() if e.domain == DOMAIN]) == 0
