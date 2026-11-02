from memory_os.core.node_stats import NodeAccessStat, NodeStatsStore
from memory_os.core.storage import FileSystemMemoryStorage


def test_node_stats_store_round_trips_shared_schema(tmp_path):
    path = tmp_path / "memory" / "node_stats.json"
    store = NodeStatsStore(path, FileSystemMemoryStorage())

    store.record_access(["fact:one", "fact:one"], accessed_at="2026-07-18T12:00:00Z")
    store.record_access(["fact:one"], accessed_at="2026-07-18T13:00:00Z")

    assert store.load() == {
        "fact:one": NodeAccessStat(count=2, last_accessed="2026-07-18T13:00:00Z")
    }


def test_node_stats_store_normalizes_invalid_entries(tmp_path):
    path = tmp_path / "memory" / "node_stats.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"fact:one":{"count":"bad"},"fact:two":null}', encoding="utf-8")

    assert NodeStatsStore(path).load() == {
        "fact:one": NodeAccessStat(),
        "fact:two": NodeAccessStat(),
    }
