"""Docker helpers for SWE-bench prediction runs."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class Container:
    container_id: str
    image: str


def resolve_image(instance: dict[str, Any]) -> str:
    for key in ("docker_image", "image_name", "image"):
        value = instance.get(key)
        if value:
            return str(value)
    instance_id = str(instance["instance_id"]).replace("__", "_1776_")
    return f"docker.io/swebench/sweb.eval.x86_64.{instance_id}:latest".lower()


def start_container(image: str, timeout: int, docker_executable: str = "docker") -> Container:
    try:
        result = subprocess.run(
            [docker_executable, "run", "-d", "--rm", "-w", "/testbed", image, "sleep", "2h"],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode_timeout_part(exc.stdout)
        stderr = _decode_timeout_part(exc.stderr)
        raise RuntimeError(f"docker run timed out for {image}: {stderr or stdout}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"docker run failed for {image}: {detail}")
    return Container(container_id=result.stdout.strip(), image=image)


def run_shell(
    container: Container,
    command: str,
    timeout: int,
    docker_executable: str = "docker",
) -> CommandResult:
    try:
        result = subprocess.run(
            [
                docker_executable,
                "exec",
                "-w",
                "/testbed",
                container.container_id,
                "bash",
                "-lc",
                command,
            ],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout=_decode_timeout_part(exc.stdout),
            stderr=_decode_timeout_part(exc.stderr),
            timed_out=True,
        )
    return CommandResult(
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=False,
    )


def stop_container(container: Container, docker_executable: str = "docker") -> None:
    try:
        subprocess.run(
            [docker_executable, "rm", "-f", container.container_id],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return


def _decode_timeout_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
