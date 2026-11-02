from memory_os.modules.exporter import PolyglotExporter


def test_draft_node_does_not_materialize_agent_facing_files(tmp_path):
    exporter = PolyglotExporter(tmp_path)

    exporter.export_node(
        "rule:draft",
        "rule",
        "Never apply an unverified rule.",
        ["evidence.md"],
        status="draft",
    )

    assert not (tmp_path / ".cursor" / "rules" / "rule:draft.mdc").exists()
    assert not (tmp_path / ".claude" / "skills" / "rule:draft.md").exists()
    assert not (tmp_path / "agent_context" / "knowledge" / "rule:draft").exists()


def test_verified_node_materializes_all_agent_facing_files(tmp_path):
    exporter = PolyglotExporter(tmp_path)

    exporter.export_node(
        "rule:verified",
        "rule",
        "Apply only after verification.",
        ["evidence.md"],
        status="verified",
    )

    assert (tmp_path / ".cursor" / "rules" / "rule:verified.mdc").exists()
    assert (tmp_path / ".claude" / "skills" / "rule:verified.md").exists()
    assert (tmp_path / "agent_context" / "knowledge" / "rule:verified").is_dir()
