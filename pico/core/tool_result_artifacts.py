"""Artifact-backed rendering for long tool results.

Large tool outputs are written to run artifacts while the prompt receives a
bounded observation with an artifact reference. This protects prompt budget
without mutating the original session history.
"""

import hashlib

from .workspace import clip

INLINE_TOOL_OUTPUT_LIMIT = 1000


def prepare_tool_result_observation(agent, name, full_result):
    full_result = str(full_result)
    metadata = {
        "original_chars": len(full_result),
        "content_sha256": hashlib.sha256(full_result.encode("utf-8")).hexdigest(),
        "full_output_artifact": "",
    }
    if len(full_result) <= INLINE_TOOL_OUTPUT_LIMIT:
        return clip(full_result), metadata
    task_state = getattr(agent, "current_task_state", None)
    if task_state is None:
        return clip(full_result, INLINE_TOOL_OUTPUT_LIMIT), metadata
    path = agent.run_store.write_text_artifact(task_state, f"{name}-output", full_result)
    relative = agent.run_store.artifact_ref(task_state, path)
    metadata["full_output_artifact"] = relative
    return (
        f"full output saved: {relative}\n"
        + clip(full_result, INLINE_TOOL_OUTPUT_LIMIT),
        metadata,
    )
