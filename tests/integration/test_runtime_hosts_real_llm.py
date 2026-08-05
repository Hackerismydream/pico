from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

_HOSTS = ("cli", "tui", "gateway")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBE_SOURCE = Path(__file__).with_name("_runtime_hosts_probe.py")
_ENV_ALLOWLIST = {
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NIX_SSL_CERT_FILE",
    "PATH",
    "PATHEXT",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "WINDIR",
}
_NETWORK_ENV_ALLOWLIST = {
    "ALL_PROXY",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "REQUESTS_CA_BUNDLE",
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _uv_binary() -> str:
    configured = os.environ.get("PICO_UV_BIN")
    candidates = [
        configured,
        shutil.which("uv"),
        "/opt/homebrew/bin/uv",
        str(Path.home() / ".local" / "bin" / "uv"),
        str(Path.home() / ".cargo" / "bin" / "uv"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    pytest.fail("infrastructure_failure: uv executable not found")


def _wheel(*, required: bool) -> Path:
    raw = os.environ.get("PICO_WHEEL", "")
    if not raw:
        if required:
            pytest.fail("configuration_failure: PICO_WHEEL is required")
        pytest.skip("PICO_WHEEL is not set")
    path = Path(raw)
    if not path.is_absolute():
        pytest.fail("configuration_failure: PICO_WHEEL must be an absolute path")
    path = path.resolve()
    if not path.is_file() or path.suffix != ".whl":
        pytest.fail(f"configuration_failure: PICO_WHEEL is not a wheel file: {path}")
    return path


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _safe_text(text: str, secrets: tuple[str, ...]) -> str:
    safe = text
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "<redacted>")
    return safe


def _run_install(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("infrastructure_failure: wheel installation timed out")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-2000:]
        pytest.fail(f"installation_failure: {_safe_text(detail, ())}")


def _install_wheel(tmp_path: Path, wheel: Path) -> tuple[Path, Path]:
    uv = _uv_binary()
    root = tmp_path / "wheel-env"
    cwd = tmp_path / "install-cwd"
    cwd.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    _run_install(
        [uv, "venv", "--python", sys.executable, "--no-project", str(root)],
        cwd=cwd,
        env=env,
    )
    python = _venv_python(root)
    _run_install(
        [uv, "pip", "install", "--python", str(python), "--strict", str(wheel)],
        cwd=cwd,
        env=env,
    )
    _run_install(
        [uv, "pip", "check", "--python", str(python)],
        cwd=cwd,
        env=env,
    )
    return root.resolve(), python.absolute()


def _probe_environment(home: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _ENV_ALLOWLIST or key.startswith("LC_") or key.upper() in _NETWORK_ENV_ALLOWLIST
    }
    env["PYTHONPATH"] = ""
    env["PYTHONNOUSERSITE"] = "1"
    env["HOME"] = str(home)
    env["PICO_HOME"] = str(home / ".pico")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["NO_COLOR"] = "1"
    return env


def test_probe_environment_is_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
    monkeypatch.setenv("KUBECONFIG", "/tmp/kubeconfig")
    monkeypatch.setenv("DOCKER_CONFIG", "/tmp/docker")
    monkeypatch.setenv("PICO_LIVE_API_KEY", "parent-secret")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7890")

    env = _probe_environment(tmp_path)

    assert "SSH_AUTH_SOCK" not in env
    assert "KUBECONFIG" not in env
    assert "DOCKER_CONFIG" not in env
    assert "PICO_LIVE_API_KEY" not in env
    assert env["https_proxy"] == "http://127.0.0.1:7890"
    assert env["PYTHONPATH"] == ""
    assert env["PYTHONNOUSERSITE"] == "1"


def _parse_probe(
    completed: subprocess.CompletedProcess[str],
    secrets: tuple[str, ...],
) -> dict[str, Any]:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        detail = _safe_text((completed.stderr or "")[-1000:], secrets)
        return {
            "status": "failed",
            "reason": "missing_probe_result",
            "detail": detail,
        }
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {
            "status": "failed",
            "reason": "invalid_probe_result",
            "detail": _safe_text(lines[-1][-1000:], secrets),
        }
    if completed.returncode != 0 and result.get("status") == "passed":
        return {
            "status": "failed",
            "reason": "probe_exit_nonzero",
            "exit_code": completed.returncode,
        }
    return result


@pytest.mark.parametrize(
    ("returncode", "stdout", "reason"),
    [
        (9, '{"status": "passed"}\n', "probe_exit_nonzero"),
        (1, "", "missing_probe_result"),
        (1, "not-json\n", "invalid_probe_result"),
    ],
)
def test_parse_probe_classifies_child_protocol_failures_as_product_failures(
    returncode: int,
    stdout: str,
    reason: str,
) -> None:
    completed = subprocess.CompletedProcess(
        args=["probe"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )

    result = _parse_probe(completed, ())

    assert result["status"] == "failed"
    assert result["reason"] == reason


def _run_hosts(
    *,
    tmp_path: Path,
    environment_root: Path,
    python: Path,
    provider: str,
    model: str,
    api_key: str,
    api_base: str,
    sentinel: str,
    mode: str,
    timeout: int,
) -> list[dict[str, Any]]:
    probe = tmp_path / "runtime-hosts-probe.py"
    shutil.copyfile(_PROBE_SOURCE, probe)
    probe_cwd = tmp_path / "probe-cwd"
    probe_cwd.mkdir()
    results: list[dict[str, Any]] = []
    for host in _HOSTS:
        home = tmp_path / f"{host}-home"
        home.mkdir()
        env = _probe_environment(home)
        env.update(
            {
                "PICO_LIVE_PROVIDER": provider,
                "PICO_LIVE_MODEL": model,
                "PICO_LIVE_API_KEY": api_key,
                "PICO_PROBE_MODE": mode,
                "PICO_PROBE_SENTINEL": sentinel,
                "PICO_PROBE_WORKSPACE": str(home / "workspace"),
            }
        )
        if api_base:
            env["PICO_LIVE_BASE_URL"] = api_base
        try:
            completed = subprocess.run(
                [str(python), str(probe), "--host", host],
                cwd=probe_cwd,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "status": "inconclusive",
                    "reason": "probe_timeout",
                    "host": host,
                }
            )
            continue
        except OSError as exc:
            results.append(
                {
                    "status": "infrastructure_failure",
                    "reason": "probe_launch_error",
                    "host": host,
                    "error_type": type(exc).__name__,
                }
            )
            continue
        result = _parse_probe(completed, (api_key,))
        result.setdefault("host", host)
        module_raw = result.get("installed_module")
        if module_raw:
            module = Path(str(module_raw)).resolve()
            if not module.is_relative_to(environment_root) or module.is_relative_to(_REPO_ROOT):
                result["status"] = "failed"
                result["reason"] = "checkout_import_detected"
        results.append(result)
    return results


def test_run_hosts_classifies_unstructured_timeouts_as_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _timeout(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", _timeout)

    results = _run_hosts(
        tmp_path=tmp_path,
        environment_root=tmp_path / "wheel-env",
        python=tmp_path / "wheel-env/bin/python",
        provider="deepseek",
        model="deepseek/deepseek-chat",
        api_key="test-key",
        api_base="",
        sentinel="sentinel",
        mode="live",
        timeout=1,
    )

    assert [result["status"] for result in results] == ["inconclusive"] * 3
    assert [result["reason"] for result in results] == ["probe_timeout"] * 3


def _assert_passed(results: list[dict[str, Any]], *, wheel: Path) -> None:
    failed = [result for result in results if result.get("status") != "passed"]
    if failed:
        evidence = {
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "results": results,
        }
        pytest.fail(json.dumps(evidence, indent=2, sort_keys=True))
    assert {result["host"] for result in results} == set(_HOSTS)
    assert {result["stream_mode"] for result in results if result["host"] == "tui"} == {True}
    assert {result["stream_mode"] for result in results if result["host"] in {"cli", "gateway"}} == {False}
    assert all(result["usage"]["total_tokens"] > 0 for result in results)
    assert all(result["tool_calls"] >= 1 for result in results)
    assert all(result["tool_failures"] == 0 for result in results)
    assert all(result["tool_names"] == ["read_file"] for result in results)
    assert all(result["output_verified"] is True for result in results)


class _EndpointState:
    def __init__(self, sentinel: str) -> None:
        self.sentinel = sentinel
        self.requests: list[dict[str, Any]] = []


def _handler(state: _EndpointState):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            messages = payload.get("messages") or []
            tool_names = sorted(
                str(tool.get("function", {}).get("name"))
                for tool in payload.get("tools") or []
                if tool.get("type") == "function" and tool.get("function", {}).get("name")
            )
            tool_messages = [message for message in messages if message.get("role") == "tool"]
            has_tool_result = bool(tool_messages)
            tool_result_verified = has_tool_result and state.sentinel in str(tool_messages[-1].get("content", ""))
            stream = bool(payload.get("stream"))
            state.requests.append(
                {
                    "stream": stream,
                    "has_tool_result": has_tool_result,
                    "tool_result_verified": tool_result_verified,
                    "tool_names": tool_names,
                }
            )
            created = int(time.time())
            response_id = f"chatcmpl-{len(state.requests)}"
            if has_tool_result:
                content = state.sentinel if tool_result_verified else "INVALID_TOOL_RESULT"
                finish_reason = "stop"
                delta = {"role": "assistant", "content": content}
                message = {"role": "assistant", "content": content}
            elif "read_file" in tool_names:
                finish_reason = "tool_calls"
                tool_call = {
                    "id": "call_read_sentinel",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "sentinel.txt"}),
                    },
                }
                delta = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"index": 0, **tool_call}],
                }
                message = {"role": "assistant", "content": None, "tool_calls": [tool_call]}
            else:
                content = "READ_FILE_TOOL_NOT_EXPOSED"
                finish_reason = "stop"
                delta = {"role": "assistant", "content": content}
                message = {"role": "assistant", "content": content}

            usage = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
            if not stream:
                body = json.dumps(
                    {
                        "id": response_id,
                        "object": "chat.completion",
                        "created": created,
                        "model": payload.get("model", "probe-model"),
                        "choices": [
                            {
                                "index": 0,
                                "message": message,
                                "finish_reason": finish_reason,
                            }
                        ],
                        "usage": usage,
                    }
                ).encode()
                self._send(body, "application/json")
                return

            chunks = [
                {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": payload.get("model", "probe-model"),
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": payload.get("model", "probe-model"),
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
                    "usage": usage,
                },
            ]
            body = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            self._send(body, "text/event-stream")

    return Handler


@pytest.mark.external_runtime
def test_runtime_hosts_from_installed_wheel(tmp_path: Path) -> None:
    wheel = _wheel(required=False)
    environment_root, python = _install_wheel(tmp_path, wheel)
    sentinel = f"PICO_WHEEL_{uuid.uuid4().hex}"
    state = _EndpointState(sentinel)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        results = _run_hosts(
            tmp_path=tmp_path,
            environment_root=environment_root,
            python=python,
            provider="custom",
            model="probe-model",
            api_key="local-test-key",
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            sentinel=sentinel,
            mode="deterministic",
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    _assert_passed(results, wheel=wheel)
    assert len(state.requests) == 6
    assert sum(request["stream"] for request in state.requests) == 2
    assert all(request["tool_names"] == ["read_file"] for request in state.requests)
    assert all(request["tool_result_verified"] for request in state.requests if request["has_tool_result"])


@pytest.mark.external_runtime
@pytest.mark.real_llm
def test_runtime_hosts_real_llm(tmp_path: Path) -> None:
    required = _truthy(os.environ.get("PICO_LIVE_REQUIRED"))
    wheel = _wheel(required=required)
    api_key = os.environ.get("PICO_LIVE_API_KEY", "")
    if not api_key:
        if required:
            pytest.fail("configuration_failure: PICO_LIVE_API_KEY is required")
        pytest.skip("PICO_LIVE_API_KEY is not set")

    environment_root, python = _install_wheel(tmp_path, wheel)
    provider = os.environ.get("PICO_LIVE_PROVIDER", "deepseek")
    model = os.environ.get("PICO_LIVE_MODEL", "deepseek/deepseek-chat")
    api_base = os.environ.get("PICO_LIVE_BASE_URL", "")
    timeout = int(os.environ.get("PICO_LIVE_TIMEOUT_SECONDS", "180"))
    results = _run_hosts(
        tmp_path=tmp_path,
        environment_root=environment_root,
        python=python,
        provider=provider,
        model=model,
        api_key=api_key,
        api_base=api_base,
        sentinel=f"PICO_LIVE_{uuid.uuid4().hex}",
        mode="live",
        timeout=timeout,
    )

    _assert_passed(results, wheel=wheel)
    assert {result["provider"] for result in results} == {provider}
    assert {result["model"] for result in results} == {model}
