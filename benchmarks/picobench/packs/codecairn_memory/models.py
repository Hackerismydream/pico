from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeCairnMemoryTask:
    task_id: str
    prior_session_id: str
    evaluation_session_id: str
    learning_prompt: str
    memory_query: str
    evaluation_prompt: str
    output_file: str
    expected_key: str
    expected_value: str
