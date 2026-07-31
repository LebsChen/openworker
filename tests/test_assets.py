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


def test_scope_matches_nested_and_windows_remote_workspaces(tmp_path):
    store = AssetStore("knowledge", tmp_path / "knowledge")
    store.save(
        {
            "name": "nested",
            "description": "Nested",
            "scope": "project",
            "project": "/workspace/project",
        }
    )
    store.save(
        {
            "name": "windows",
            "description": "Windows",
            "scope": "project",
            "project": r"C:\Users\dev\project",
        }
    )
    assert store.get("nested", workspace="/workspace/project/src") is not None
    assert (
        store.get(
            "windows",
            workspace=r"C:\Users\dev\project\src",
            path_style="windows",
        )
        is not None
    )


def test_frontmatter_round_trips_quoted_description_and_rejects_newlines(tmp_path):
    store = AssetStore("knowledge", tmp_path / "knowledge")
    item = store.save(
        {
            "name": "quoted",
            "description": '  "quoted: value"  ',
            "body": "body",
            "trigger": "manual",
        }
    )
    assert store.get("quoted").description == '"quoted: value"'
    for field in ("name", "description"):
        data = {"name": "valid", "description": "ok", "body": ""}
        data[field] = "bad\nvalue"
        try:
            store.save(data)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{field} newline was accepted")


def test_knowledge_trigger_is_validated_and_defaults_to_manual(tmp_path):
    store = AssetStore("knowledge", tmp_path / "knowledge")
    assert store.save({"name": "manual", "description": ""})["trigger"] == "manual"
    try:
        store.save({"name": "bad", "description": "", "trigger": "hourly"})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid trigger was accepted")


def test_always_knowledge_is_injected_into_system_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("COWORKER_STATE_DIR", str(tmp_path / "state"))
    store = AssetStore("knowledge", tmp_path / "state" / "knowledge")
    store.save(
        {
            "name": "always-note",
            "description": "Injected note",
            "body": "This body must be in the system prompt.",
            "trigger": "always",
        }
    )

    from coworker.agent import build_engine
    from coworker.agents import chat_agent

    class Provider:
        def complete(self, **kwargs):
            raise AssertionError("completion should not run")

        def capabilities(self, model):
            return None

    engine = build_engine(agent=chat_agent(), provider=Provider())
    assert "This body must be in the system prompt." in engine.messages[0]["content"]
