from coworker.assets import AssetStore, PLAYBOOK_TEMPLATE


def test_asset_store_frontmatter_scope_and_progressive_metadata(tmp_path):
    store = AssetStore("knowledge", tmp_path / "knowledge")
    store.save(
        {
            "name": "global-note",
            "description": "Always useful",
            "body": "Remember this.",
            "trigger": "always",
        }
    )
    store.save(
        {
            "name": "project-note",
            "description": "Project only",
            "body": "Project detail.",
            "scope": "project",
            "project": "/remote/workspace",
        }
    )
    assert [x["name"] for x in store.list(workspace="/remote/workspace")] == [
        "global-note",
        "project-note",
    ]
    assert [x["name"] for x in store.list(workspace="/other")] == ["global-note"]
    assert "Remember this." not in store.list(workspace="/remote/workspace")[0]
    assert store.get("project-note", workspace="/other") is None


def test_playbook_create_uses_five_part_template(tmp_path):
    store = AssetStore("playbooks", tmp_path / "playbooks")
    item = store.save({"name": "deploy", "description": "Deploy safely"})
    assert item["body"].startswith("# deploy")
    for section in ("Overview", "What to do", "Advice and pointers", "Specifications", "Forbidden actions"):
        assert f"## {section}" in item["body"]
    assert PLAYBOOK_TEMPLATE
