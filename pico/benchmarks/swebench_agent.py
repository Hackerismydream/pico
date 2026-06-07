"""Shell-only SWE-bench agent loop."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Callable

from ..providers.base import complete_model
from .swebench_docker import CommandResult


RunShell = Callable[[str], CommandResult]
FINAL_DIFF_COMMAND = "git -c core.fileMode=false diff -- ."


@dataclass
class Trajectory:
    instance_id: str
    model: str
    image: str = ""
    setup_error: str = ""
    model_error: str = ""
    exit_status: str = "submitted"
    model_patch_chars: int = 0
    model_patch: str = ""
    steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("model_patch", None)
        return payload


class SWEBenchAgent:
    def __init__(self, model_client, *, model: str, max_steps: int, max_new_tokens: int):
        self.model_client = model_client
        self.model = model
        self.max_steps = int(max_steps)
        self.max_new_tokens = int(max_new_tokens)

    def run(self, instance: dict, run_shell: RunShell, *, image: str = "") -> Trajectory:
        trajectory = Trajectory(
            instance_id=str(instance.get("instance_id", "")),
            model=self.model,
            image=image,
        )
        transcript = [{"role": "user", "content": initial_prompt(instance)}]
        for _ in range(self.max_steps):
            prompt = _render_transcript(transcript)
            try:
                result = complete_model(self.model_client, prompt, self.max_new_tokens)
            except Exception as exc:
                trajectory.exit_status = "model_error"
                trajectory.model_error = str(exc)
                trajectory.steps.append({"model_error": str(exc)})
                break
            text = result.text
            step = {
                "model_output": text,
                "metadata": result.metadata,
                "parse_error": "",
                "tool_call": {},
                "tool_result": {},
            }
            final = _extract_tag(text, "final")
            if final is not None:
                trajectory.exit_status = "final"
                trajectory.steps.append(step)
                break
            command = _extract_tool_command(text)
            if command is None:
                correction = (
                    "Use exactly one tool call per step: "
                    '<tool name="run_shell"><command>...</command></tool> '
                    "or finish with <final>brief summary</final>."
                )
                step["parse_error"] = correction
                trajectory.steps.append(step)
                transcript.append({"role": "assistant", "content": text})
                transcript.append({"role": "user", "content": correction})
                continue
            tool_result = run_shell(command)
            step["tool_call"] = {"name": "run_shell", "command": command}
            step["tool_result"] = _command_result_dict(tool_result)
            trajectory.steps.append(step)
            transcript.append({"role": "assistant", "content": text})
            transcript.append({"role": "user", "content": _format_command_result(tool_result)})
        else:
            trajectory.exit_status = "step_limit"

        diff = run_shell(FINAL_DIFF_COMMAND)
        trajectory.steps.append(
            {
                "model_output": "",
                "metadata": {},
                "parse_error": "",
                "tool_call": {"name": "run_shell", "command": FINAL_DIFF_COMMAND},
                "tool_result": _command_result_dict(diff),
            }
        )
        trajectory.model_patch = diff.stdout if diff.returncode == 0 else ""
        trajectory.model_patch_chars = len(trajectory.model_patch)
        if trajectory.model_patch and trajectory.exit_status in {"submitted", "final", "step_limit"}:
            trajectory.exit_status = "submitted"
        return trajectory


def initial_prompt(instance: dict) -> str:
    return "\n".join(
        [
            "You are solving a SWE-bench task inside Docker.",
            "The repository is checked out at /testbed.",
            "Use exactly one tool call per step:",
            '<tool name="run_shell"><command>...</command></tool>',
            "When done, respond with:",
            "<final>brief summary</final>",
            "Do not modify tests.",
            "Leave the final patch in git diff.",
            "",
            f"Instance: {instance.get('instance_id', '')}",
            "",
            "Problem statement:",
            str(instance.get("problem_statement", "")).strip(),
        ]
    )


def _render_transcript(transcript: list[dict]) -> str:
    return "\n\n".join(
        f"{str(item.get('role', '')).upper()}:\n{item.get('content', '')}"
        for item in transcript
    )


def _extract_tool_command(text: str) -> str | None:
    match = re.search(
        r'<tool\s+name="run_shell"\s*>(.*?)</tool>',
        text,
        flags=re.DOTALL,
    )
    if not match:
        return None
    command = _extract_tag(match.group(1), "command")
    return command.strip() if command and command.strip() else None


def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def _format_command_result(result: CommandResult) -> str:
    return (
        f"run_shell returncode={result.returncode} timed_out={result.timed_out}\n"
        f"stdout:\n{_clip(result.stdout)}\n\nstderr:\n{_clip(result.stderr)}"
    )


def _command_result_dict(result: CommandResult) -> dict:
    data = asdict(result)
    data["stdout"] = _clip(data["stdout"])
    data["stderr"] = _clip(data["stderr"])
    return data


def _clip(text: str, limit: int = 12000) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... clipped {len(text) - limit} chars ..."
