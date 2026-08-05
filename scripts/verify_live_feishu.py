#!/usr/bin/env python3
"""V-LF: orchestrate the required real Feishu tracer bullet.

Prepares a disposable PICO_HOME, runs the operator-in-the-loop live phases in
tests/integration/test_feishu_real_channel.py, then classifies, redacts, and
writes one machine-readable report. Raw logs never leave the disposable home;
only whitelisted, redacted receipt lines enter the evidence directory. See
docs/specs/channel-evidence-gates.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REQUIRED_ENV = (
    "PICO_LIVE_FEISHU_APP_ID",
    "PICO_LIVE_FEISHU_APP_SECRET",
    "PICO_LIVE_FEISHU_OPERATOR_ID",
    "PICO_LIVE_API_KEY",
)
_SECRET_ENV = ("PICO_LIVE_FEISHU_APP_SECRET", "PICO_LIVE_API_KEY")
REQUIRED_CHECKS = (
    "gateway_boot",
    "inbound_reply_text",
    "attachment_inbound",
    "media_out",
    "cron_restart_exactly_once",
)
OPTIONAL_CHECKS = ("allowlist_negative_live",)
_LIVE_TEST = "tests/integration/test_feishu_real_channel.py"
_EXCERPT_MARKERS = (
    "Feishu bot started",
    "Feishu inbound accepted:",
    "Feishu duplicate event suppressed:",
    "Feishu inbound rejected by allowlist",
    "Feishu message sent:",
    "Failed to send Feishu",
    "Feishu WebSocket error",
    "Cron: executing job",
    "Cron: job",
    "Cron: added job",
)
_ID_PATTERN = re.compile(r"\b(ou_|oc_|om_|oc-)[A-Za-z0-9]{4,}\b")
_APP_ID_PATTERN = re.compile(r"\bcli_[a-z0-9]{6,}\b")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_text(text: str) -> str:
    """Replace platform identifiers with stable digests and strip secrets.

    Applied to every byte that leaves the disposable home; secrets are
    removed even though they are never expected to appear."""
    for name in _SECRET_ENV:
        value = os.environ.get(name, "")
        if value:
            text = text.replace(value, "[redacted-secret]")
    identifiers = [os.environ.get("PICO_LIVE_FEISHU_APP_ID", ""), os.environ.get("PICO_LIVE_FEISHU_OPERATOR_ID", "")]
    for value in identifiers:
        if value:
            text = text.replace(value, f"id:{_digest(value)}")
    text = _ID_PATTERN.sub(lambda m: f"{m.group(1)}sha:{_digest(m.group(0))}", text)
    text = _APP_ID_PATTERN.sub(lambda m: f"cli_sha:{_digest(m.group(0))}", text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def excerpt_lines(log_text: str) -> list[str]:
    """Whitelist receipt lines so message bodies never enter evidence."""
    return [line for line in log_text.splitlines() if any(marker in line for marker in _EXCERPT_MARKERS)]


def aggregate(checks: dict[str, dict], *, credentials_present: bool, required: bool) -> str:
    if not credentials_present:
        return "failed" if required else "skipped"
    for name in REQUIRED_CHECKS:
        if checks.get(name, {}).get("status") != "passed":
            return "failed"
    return "passed"


def build_criteria(checks: dict[str, dict]) -> dict[str, dict]:
    def live_or_deterministic(check: str, fallback: str) -> dict[str, str]:
        if checks.get(check, {}).get("status") == "passed":
            return {"evidence_class": "both", "check": check}
        return {"evidence_class": "deterministic", "check": fallback}

    cron = checks.get("cron_restart_exactly_once", {})
    reconnect_live = bool(cron.get("websocket_restarted")) and cron.get("status") == "passed"
    return {
        "real_inbound_outbound": {"evidence_class": "live", "check": "inbound_reply_text"},
        "allowlist": live_or_deterministic("allowlist_negative_live", "V-C0 adapter early-gate and Intake tests"),
        "duplicate_events": {
            "evidence_class": "deterministic",
            "check": "V-C0 dedup suppression tests",
        },
        "disconnect_reconnect": {
            "evidence_class": "both" if reconnect_live else "deterministic",
            "check": "cron_restart_exactly_once" if reconnect_live else "V-C0 supervised reconnect tests",
        },
        "error_receipts": {
            "evidence_class": "deterministic",
            "check": "V-C0 send failure logging tests",
        },
        "attachment_and_media_out": {
            "evidence_class": "live",
            "check": "attachment_inbound, media_out",
        },
        "cron_exactly_once": {
            "evidence_class": "live",
            "check": "cron_restart_exactly_once",
        },
    }


def _tool(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required tool not found on PATH: {name}")
    return resolved


def _prepare_wheel_entrypoint(root: Path, wheel: str) -> str:
    venv_dir = root / "wheel-env"
    uv = _tool("uv")
    subprocess.run([uv, "venv", str(venv_dir)], check=True, capture_output=True, text=True)
    subprocess.run(
        [uv, "pip", "install", "--python", str(venv_dir / "bin" / "python"), wheel],
        check=True,
        capture_output=True,
        text=True,
    )
    entrypoint = venv_dir / "bin" / "pico"
    if not entrypoint.is_file():
        raise RuntimeError(f"installed wheel exposes no pico entrypoint at {entrypoint}")
    return str(entrypoint)


def _tee_pytest(command: list[str], env: dict[str, str], log_path: Path, timeout: float) -> int:
    with log_path.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(
            command,
            cwd=_REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        deadline = time.monotonic() + timeout
        if process.stdout is None:
            raise RuntimeError("pytest subprocess exposes no stdout pipe")
        for line in process.stdout:
            print(line, end="", flush=True)
            sink.write(line)
            if time.monotonic() > deadline:
                process.kill()
                sink.write("\ninfrastructure_failure: harness watchdog timeout\n")
                break
        return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=3600.0)
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    required = os.environ.get("PICO_LIVE_FEISHU_REQUIRED") == "1"
    credentials_present = all(os.environ.get(name) for name in _REQUIRED_ENV)

    checks: dict[str, dict] = {}
    meta: dict[str, Any] = {}
    logs: dict[str, dict] = {}
    runtime_source = "checkout"
    exit_code: int | None = None

    if credentials_present:
        scratch_root = Path(tempfile.mkdtemp(prefix="pico-vlf-run-"))
        home = scratch_root / "home"
        scratch = scratch_root / "scratch.json"
        env = os.environ.copy()
        env["PICO_VLF_HOME"] = str(home)
        env["PICO_VLF_SCRATCH"] = str(scratch)
        wheel = os.environ.get("PICO_WHEEL", "")
        try:
            if wheel:
                env["PICO_VLF_ENTRYPOINT"] = _prepare_wheel_entrypoint(scratch_root, wheel)
                runtime_source = "installed_wheel"
            raw_pytest_log = scratch_root / "pytest.log"
            command = [
                sys.executable,
                "-m",
                "pytest",
                _LIVE_TEST,
                "-q",
                "-s",
                "-rs",
                "--strict-markers",
                "-m",
                "real_channel",
                "-p",
                "no:cacheprovider",
            ]
            exit_code = _tee_pytest(command, env, raw_pytest_log, args.timeout)

            if scratch.is_file():
                payload = json.loads(scratch.read_text(encoding="utf-8"))
                checks = payload.get("checks", {})
                meta = payload.get("meta", {})

            pytest_log = output_root / "live-pytest.log"
            pytest_log.write_text(
                redact_text(raw_pytest_log.read_text(encoding="utf-8", errors="replace")),
                encoding="utf-8",
            )
            logs["pytest"] = {"log": pytest_log.name, "log_sha256": _sha256_file(pytest_log)}

            gateway_log = home / "logs" / "gateway.log"
            if gateway_log.is_file():
                excerpt = output_root / "gateway-receipts.log"
                lines = excerpt_lines(gateway_log.read_text(encoding="utf-8", errors="replace"))
                excerpt.write_text(redact_text("\n".join(lines)) + "\n", encoding="utf-8")
                logs["gateway_receipts"] = {
                    "log": excerpt.name,
                    "log_sha256": _sha256_file(excerpt),
                }
        finally:
            shutil.rmtree(scratch_root, ignore_errors=True)

    status = aggregate(checks, credentials_present=credentials_present, required=required)
    commit = subprocess.run(
        [_tool("git"), "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    report = {
        "schema": "pico.feishu.live.evidence.v1",
        "gate": "V-LF",
        "status": status,
        "live_mode": "required" if required else "optional",
        "runtime_source": runtime_source,
        "commit": commit,
        "pytest_exit_code": exit_code,
        "credentials_present": credentials_present,
        "checks": redact_value(checks),
        "criteria": build_criteria(checks),
        "meta": redact_value(meta),
        "logs": logs,
    }
    report_path = output_root / "feishu-live-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"V-LF {status}: {report_path}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
