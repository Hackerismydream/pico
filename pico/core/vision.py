"""Vision inspection helper for image-aware tools."""

from __future__ import annotations

from ..providers.base import complete_model
from .content_blocks import ModelInput
from .media import load_workspace_image


def inspect_image_with_model(agent, path, question, profile="general", output_schema=""):
    loaded = load_workspace_image(agent, path)
    prompt = image_inspection_prompt(
        loaded.metadata["path"], question, profile, output_schema
    )
    model_client = resolve_vision_model_client(agent)
    result = complete_model(
        model_client,
        ModelInput(text=prompt, images=[loaded.block]),
        agent.max_new_tokens,
    )
    media_ref = dict(loaded.metadata)
    task_state = getattr(agent, "current_task_state", None)
    if task_state is not None:
        artifact = agent.run_store.write_binary_artifact(
            task_state,
            "image",
            loaded.block.data,
            image_suffix(loaded.block.mime_type),
        )
        media_ref["artifact_ref"] = agent.run_store.artifact_ref(task_state, artifact)
    else:
        media_ref["artifact_ref"] = ""
    agent._pending_tool_result_metadata = {
        "media_refs": [media_ref],
        "vision_completion_metadata": dict(result.metadata),
    }
    return (
        f"image inspected: {loaded.metadata['path']}\n"
        f"profile: {profile or 'general'}\n"
        f"summary:\n{result.text}"
    )


def image_inspection_prompt(path, question, profile, output_schema):
    lines = [
        "Inspect this workspace image for a coding-agent task.",
        f"Image path: {path}",
        f"Inspection profile: {profile or 'general'}",
        f"Question: {question}",
    ]
    schema = str(output_schema or "").strip()
    if schema:
        lines.append(f"Return shape: {schema}")
    lines.append("Return concise, task-useful observations. Do not mention base64.")
    return "\n".join(lines)


def resolve_vision_model_client(agent):
    model_client = getattr(agent, "vision_model_client", None)
    if model_client is not None:
        return model_client
    factory = getattr(agent, "vision_model_client_factory", None)
    if factory is not None:
        model_client = factory()
        agent.vision_model_client = model_client
        return model_client
    return agent.model_client


def image_suffix(mime_type):
    return {
        "image/gif": ".gif",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(str(mime_type), ".img")
