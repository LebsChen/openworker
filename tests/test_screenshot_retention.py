from __future__ import annotations

from coworker.conversations import ConversationStore
from coworker.engine import SCREENSHOT_HISTORY_LIMIT, TurnEngine
from coworker.permissions import Mode, PermissionEngine
from coworker.providers import ModelCapabilities, ProviderClient
from coworker.sessions import SessionRecord
from coworker.tools import ToolRegistry


class VisionProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise AssertionError("not expected to call provider")

    def capabilities(self, model):
        return ModelCapabilities(vision=True)


def _screenshot(index: int) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"screenshot {index}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{index}"}},
        ],
        "_screenshot_image": True,
    }


def test_screenshot_retention_is_outbound_only_and_survives_reload(tmp_path):
    messages = [_screenshot(index) for index in range(SCREENSHOT_HISTORY_LIMIT + 1)]
    store = ConversationStore(tmp_path)
    store.save(
        SessionRecord(
            session_id="screenshots",
            workspace=str(tmp_path),
            model="test",
            mode=Mode.INTERACTIVE.value,
            messages=messages,
        )
    )
    restored = store.load("screenshots")
    assert restored is not None
    assert len(restored.messages) == SCREENSHOT_HISTORY_LIMIT + 1
    assert all(message.get("_screenshot_image") is True for message in restored.messages)
    assert all(isinstance(message["content"], list) for message in restored.messages)

    engine = TurnEngine(
        provider=VisionProvider(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="test",
        messages=restored.messages,
    )
    outbound = engine._outbound_messages()

    assert len(outbound) == SCREENSHOT_HISTORY_LIMIT + 1
    assert outbound[0]["content"] == (
        "[screenshot from an earlier turn — take a new one if you need to look again]"
    )
    assert all("_screenshot_image" not in message for message in outbound)
    assert all(isinstance(message["content"], list) for message in outbound[1:])
    assert all(isinstance(message["content"], list) for message in engine.messages)
