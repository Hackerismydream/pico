import json
import urllib.request

import pytest

import pico.cli as pico_cli
from pico.core.runtime import Pico
from pico.core.session_store import SessionStore
from pico.core.workspace import WorkspaceContext
from pico.providers.clients import AnthropicCompatibleModelClient, OpenAICompatibleModelClient
from pico.testing import ScriptedModelClient


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeResponse:
    def __init__(self, payload, content_type="application/json"):
        self.payload = payload
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class RecordingVisionClient(ScriptedModelClient):
    def __init__(self, outputs):
        super().__init__(outputs)


def build_agent(tmp_path, model_client=None):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=model_client or RecordingVisionClient(["A small red chart."]),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        max_steps=4,
    )


def write_png(tmp_path, name="chart.png"):
    path = tmp_path / name
    path.write_bytes(PNG_BYTES)
    return path


def test_openai_client_sends_image_blocks_in_responses_payload(monkeypatch):
    from pico.core.content_blocks import ImageBlock, ModelInput

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"output_text": "<final>ok</final>"})

    client = OpenAICompatibleModelClient(
        model="vision-model",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=None,
        timeout=30,
    )
    image = ImageBlock(
        path="chart.png",
        mime_type="image/png",
        data=PNG_BYTES,
        sha256="abc123",
    )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = client.complete(ModelInput(text="Describe it.", images=[image]), 64)

    assert result == "<final>ok</final>"
    content = captured["body"]["input"][0]["content"]
    assert content[0] == {"type": "input_text", "text": "Describe it."}
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert "abc123" not in content[1]["image_url"]
    assert client.last_completion_metadata["image_input_count"] == 1


def test_anthropic_client_sends_image_blocks_in_messages_payload(monkeypatch):
    from pico.core.content_blocks import ImageBlock, ModelInput

    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"content": [{"type": "text", "text": "<final>ok</final>"}]})

    client = AnthropicCompatibleModelClient(
        model="claude-vision",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=None,
        timeout=30,
    )
    image = ImageBlock(
        path="chart.png",
        mime_type="image/png",
        data=PNG_BYTES,
        sha256="abc123",
    )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = client.complete(ModelInput(text="Describe it.", images=[image]), 64)

    assert result == "<final>ok</final>"
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["type"] == "base64"
    assert content[0]["source"]["media_type"] == "image/png"
    assert content[0]["source"]["data"]
    assert content[1] == {"type": "text", "text": "Describe it."}
    assert client.last_completion_metadata["image_input_count"] == 1


def test_deepseek_profile_defaults_to_openai_vision_provider(tmp_path, monkeypatch):
    from pico.config import resolve_provider_config

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")

    config = resolve_provider_config("deepseek", start=tmp_path)

    assert config.name == "deepseek"
    assert config.model == "deepseek-v4-pro"
    assert config.supports_vision is False
    assert config.vision_provider == "openai"


def test_build_agent_uses_separate_vision_provider_for_deepseek(tmp_path, monkeypatch):
    args = pico_cli.build_arg_parser().parse_args(
        ["--cwd", str(tmp_path), "--provider", "deepseek"]
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("OPENAI_MODEL", "vision-model")
    monkeypatch.setenv("OPENAI_API_BASE", "https://vision.example/v1")

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(pico_cli, "AnthropicCompatibleModelClient", lambda **kwargs: ("anthropic", kwargs))
        patcher.setattr(pico_cli, "OpenAICompatibleModelClient", lambda **kwargs: ("openai", kwargs))
        agent = pico_cli.build_agent(args)
        vision_client = agent.vision_model_client_factory()

    assert agent.model_client[0] == "anthropic"
    assert agent.model_client[1]["model"] == "deepseek-v4-pro"
    assert not hasattr(agent, "vision_model_client")
    assert vision_client[0] == "openai"
    assert vision_client[1]["model"] == "vision-model"
    assert vision_client[1]["base_url"] == "https://vision.example/v1"


def test_inspect_image_uses_separate_vision_model_when_configured(tmp_path):
    from pico.core.content_blocks import ModelInput
    from pico.core.task_state import TaskState

    write_png(tmp_path)
    main_client = RecordingVisionClient(["unused main model output"])
    vision_client = RecordingVisionClient(["vision provider summary"])
    agent = build_agent(tmp_path, model_client=main_client)
    agent.vision_model_client = vision_client
    task_state = TaskState.create(run_id="run_direct", task_id="task_direct", user_request="inspect")
    agent.current_task_state = task_state
    agent.current_run_dir = agent.run_store.start_run(task_state)

    result = agent.run_tool(
        "inspect_image",
        {"path": "chart.png", "question": "What is shown?", "profile": "general"},
    )

    assert "vision provider summary" in result
    assert main_client.prompts == []
    assert isinstance(vision_client.prompts[0], ModelInput)
    assert vision_client.prompts[0].images[0].path == "chart.png"


def test_load_workspace_image_rejects_path_escape_and_records_safe_metadata(tmp_path):
    from pico.core.media import load_workspace_image

    write_png(tmp_path)
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(PNG_BYTES)
    agent = build_agent(tmp_path)

    loaded = load_workspace_image(agent, "chart.png")
    assert loaded.block.mime_type == "image/png"
    assert loaded.metadata["path"] == "chart.png"
    assert loaded.metadata["sha256"] == loaded.block.sha256
    assert "base64" not in json.dumps(loaded.metadata)

    with pytest.raises(ValueError, match="path escapes workspace"):
        load_workspace_image(agent, "../outside.png")


def test_run_store_writes_binary_artifact(tmp_path):
    from pico.core.task_state import TaskState

    agent = build_agent(tmp_path)
    task_state = TaskState.create(run_id="run_test", task_id="task_test", user_request="inspect")
    agent.current_run_dir = agent.run_store.start_run(task_state)

    path = agent.run_store.write_binary_artifact(task_state, "image", PNG_BYTES, ".png")
    assert path.read_bytes() == PNG_BYTES
    assert agent.run_store.artifact_ref(task_state, path).endswith(".png")


def test_inspect_image_tool_calls_model_with_model_input_and_records_media_refs(tmp_path):
    from pico.core.content_blocks import ModelInput
    from pico.core.task_state import TaskState

    write_png(tmp_path)
    client = RecordingVisionClient(["The image contains a one-pixel chart."])
    agent = build_agent(tmp_path, model_client=client)
    task_state = TaskState.create(run_id="run_direct", task_id="task_direct", user_request="inspect")
    agent.current_task_state = task_state
    agent.current_run_dir = agent.run_store.start_run(task_state)

    result = agent.run_tool(
        "inspect_image",
        {"path": "chart.png", "question": "What is shown?", "profile": "general"},
    )

    assert "The image contains a one-pixel chart." in result
    assert isinstance(client.prompts[0], ModelInput)
    assert client.prompts[0].images[0].mime_type == "image/png"
    media_refs = agent._last_tool_result_metadata["media_refs"]
    assert media_refs[0]["path"] == "chart.png"
    assert media_refs[0]["artifact_ref"].endswith(".png")
    assert "base64" not in json.dumps(agent._last_tool_result_metadata)


def test_inspect_image_tool_trace_and_history_do_not_store_base64(tmp_path):
    write_png(tmp_path)
    client = RecordingVisionClient(
        [
            '<tool>{"name":"inspect_image","args":{"path":"chart.png","question":"Describe it"}}</tool>',
            "one-pixel image",
            "<final>Image inspected.</final>",
        ]
    )
    agent = build_agent(tmp_path, model_client=client)

    events = list(agent.engine.run_turn("inspect chart.png"))

    assert any(event["type"] == "final" for event in events)
    trace_text = (agent.current_run_dir / "trace.jsonl").read_text(encoding="utf-8")
    assert "media_refs" in trace_text
    assert "base64" not in trace_text

    prompt, metadata = agent.context_manager.build("continue")
    assert "[image]" in prompt
    assert "chart.png" in prompt
    assert "base64" not in prompt
    assert metadata["history"]["summarized_tool_count"] >= 0
