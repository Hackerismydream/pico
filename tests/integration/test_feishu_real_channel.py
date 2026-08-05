"""V-LF: the required real Feishu tracer bullet.

Runs a real Feishu bot end to end through the production Gateway path:
inbound event -> FeishuChannel -> Intake -> Spine -> AgentLoop -> DeliveryHub
-> Feishu reply, plus attachment ingestion, MediaOut delivery, and a Cron job
that survives a Gateway restart and delivers exactly once.

The live inbound stimulus is a human operator (a bot cannot message itself);
each phase prints one instruction and polls observable receipts with a
timeout. Orchestrated by scripts/verify_live_feishu.py; see
docs/specs/channel-evidence-gates.md for the design and claim boundary.

Environment: PICO_LIVE_FEISHU_APP_ID / _APP_SECRET / _OPERATOR_ID plus the
V-LP Provider variables (PICO_LIVE_API_KEY / _PROVIDER / _MODEL). Missing
credentials skip in ad-hoc runs and fail when PICO_LIVE_FEISHU_REQUIRED=1.
"""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_channel

_REQUIRED_ENV = (
    "PICO_LIVE_FEISHU_APP_ID",
    "PICO_LIVE_FEISHU_APP_SECRET",
    "PICO_LIVE_FEISHU_OPERATOR_ID",
    "PICO_LIVE_API_KEY",
)
_BOOT_MARKER = "Feishu bot started"
_ACCEPT_MARKER = "Feishu inbound accepted:"
_SENT_MARKER = "Feishu message sent:"
_CRON_EXEC_MARKER = "Cron: executing job"
_REJECT_MARKER = "Feishu inbound rejected by allowlist"
# 1x1 transparent PNG, used as the MediaOut probe artifact.
_PROBE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="
)


def _phase_timeout() -> float:
    return float(os.environ.get("PICO_LIVE_FEISHU_TIMEOUT_SECONDS", "240"))


def _require_credentials() -> None:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if not missing:
        return
    reason = f"configuration_failure: missing {', '.join(missing)}"
    if os.environ.get("PICO_LIVE_FEISHU_REQUIRED") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TracerBullet:
    """Owns the disposable PICO_HOME, the Gateway subprocess, log offsets,
    and the scratch results consumed by scripts/verify_live_feishu.py."""

    def __init__(self) -> None:
        self.operator_id = os.environ["PICO_LIVE_FEISHU_OPERATOR_ID"]
        home_override = os.environ.get("PICO_VLF_HOME", "")
        if home_override:
            self.home = Path(home_override)
            self.home.mkdir(parents=True, exist_ok=True)
            self._owns_home = False
        else:
            self.home = Path(tempfile.mkdtemp(prefix="pico-vlf-"))
            self._owns_home = True
        self.workspace = self.home / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.scratch_path = Path(os.environ.get("PICO_VLF_SCRATCH", "") or str(self.home / "vlf-scratch.json"))
        self.port = _free_port()
        self.log_path = self.home / "logs" / "gateway.log"
        self.process: subprocess.Popen | None = None
        self.boot_count = 0
        self._scratch: dict = {"checks": {}, "meta": {"gateway_port": self.port}}
        self._write_config()
        self._flush_scratch()

    def _entrypoint(self) -> list[str]:
        override = os.environ.get("PICO_VLF_ENTRYPOINT", "")
        if override:
            return [override]
        return [sys.executable, "-m", "pico"]

    def _write_config(self) -> None:
        from pico.config.pico import PicoConfig
        from pico.config.schema import Config

        provider_name = os.environ.get("PICO_LIVE_PROVIDER", "deepseek")
        config = Config()
        config.agents.defaults.workspace = str(self.workspace)
        config.agents.defaults.provider = provider_name
        config.agents.defaults.model = os.environ.get("PICO_LIVE_MODEL", "deepseek/deepseek-chat")
        config.agents.defaults.temperature = 0.0
        config.tools.restrict_to_workspace = True
        provider_config = getattr(config.providers, provider_name, None)
        if provider_config is None:
            raise ValueError(f"unsupported provider: {provider_name}")
        provider_config.api_key = os.environ["PICO_LIVE_API_KEY"]
        base_url = os.environ.get("PICO_LIVE_BASE_URL", "")
        if base_url:
            provider_config.api_base = base_url
        config.channels.feishu.enabled = True
        config.channels.feishu.app_id = os.environ["PICO_LIVE_FEISHU_APP_ID"]
        config.channels.feishu.app_secret = os.environ["PICO_LIVE_FEISHU_APP_SECRET"]
        config.channels.feishu.allow_from = [self.operator_id]
        config.channels.feishu.group_policy = "mention"
        config.gateway.port = self.port

        pico_config = PicoConfig(base=config)
        pico_config.plugins.disabled = []
        pico_config.memory.backend = None
        pico_config.skill_forge.enabled = False
        pico_config.skill_forge.router.enabled = False
        pico_config.token_wise.enabled = False
        document = config.model_dump(mode="json", by_alias=True)
        document.update(
            {
                "memory": pico_config.memory.model_dump(mode="json", by_alias=True),
                "plugins": pico_config.plugins.model_dump(mode="json", by_alias=True),
                "skillForge": pico_config.skill_forge.model_dump(mode="json", by_alias=True),
                "tokenWise": pico_config.token_wise.model_dump(mode="json", by_alias=True),
            }
        )
        config_path = self.home / "config.json"
        config_path.write_text(json.dumps(document), encoding="utf-8")
        config_path.chmod(0o600)

    # ── scratch records ────────────────────────────────────────────────

    def record(self, check: str, status: str, **details) -> None:
        self._scratch["checks"][check] = {"status": status, **details}
        self._flush_scratch()

    def meta(self, **fields) -> None:
        self._scratch["meta"].update(fields)
        self._flush_scratch()

    def _flush_scratch(self) -> None:
        self.scratch_path.parent.mkdir(parents=True, exist_ok=True)
        self.scratch_path.write_text(json.dumps(self._scratch, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # ── gateway lifecycle ──────────────────────────────────────────────

    def start_gateway(self) -> None:
        assert self.process is None
        env = os.environ.copy()
        env["PICO_HOME"] = str(self.home)
        stdout_path = self.home / f"gateway-stdout-{self.boot_count}.log"
        self.process = subprocess.Popen(
            [*self._entrypoint(), "gateway"],
            env=env,
            stdout=stdout_path.open("wb"),
            stderr=subprocess.STDOUT,
        )
        self.boot_count += 1
        deadline = time.monotonic() + 120
        url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"infrastructure_failure: gateway exited with {self.process.returncode}; see {stdout_path}"
                )
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(1)
        raise RuntimeError("infrastructure_failure: gateway /health never responded")

    def stop_gateway(self) -> None:
        if self.process is None:
            return
        self.process.send_signal(signal.SIGINT)
        try:
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None

    def close(self) -> None:
        self.stop_gateway()

    # ── observation ────────────────────────────────────────────────────

    def log_size(self) -> int:
        try:
            return self.log_path.stat().st_size
        except FileNotFoundError:
            return 0

    def log_text(self, start: int = 0, end: int | None = None) -> str:
        try:
            data = self.log_path.read_bytes()
        except FileNotFoundError:
            return ""
        return data[start:end].decode("utf-8", errors="replace")

    def wait_marker(self, pattern: str, *, offset: int, timeout: float | None = None) -> str:
        deadline = time.monotonic() + (timeout if timeout is not None else _phase_timeout())
        while time.monotonic() < deadline:
            text = self.log_text(offset)
            match = re.search(pattern, text)
            if match:
                return match.group(0)
            time.sleep(1)
        raise TimeoutError(f"inconclusive: no match for {pattern!r} within timeout")

    @staticmethod
    def instruct(text: str) -> None:
        print(f"\n{'=' * 70}\nOPERATOR ACTION REQUIRED\n{text}\n{'=' * 70}", flush=True)

    def session_text(self) -> str:
        session_dir = self.workspace / "sessions" / "feishu"
        if not session_dir.is_dir():
            return ""
        return "".join(
            path.read_text(encoding="utf-8", errors="replace") for path in sorted(session_dir.glob("*.jsonl"))
        )


@pytest.fixture(scope="module")
def bullet():
    _require_credentials()
    tracer = TracerBullet()
    try:
        yield tracer
    finally:
        errors = [
            line
            for line in tracer.log_text().splitlines()
            if "Failed to send Feishu" in line or "Feishu WebSocket error" in line or "Error adding reaction" in line
        ]
        tracer.meta(observed_error_receipts=len(errors))
        tracer.close()


def test_gateway_boot(bullet):
    offset = bullet.log_size()
    try:
        bullet.start_gateway()
        bullet.wait_marker(re.escape(_BOOT_MARKER), offset=offset, timeout=60)
    except (RuntimeError, TimeoutError) as exc:
        bullet.record("gateway_boot", "infrastructure_failure", reason=str(exc))
        pytest.fail(str(exc))
    bullet.record("gateway_boot", "passed", health=True, websocket_started=True)


def test_inbound_reply_text(bullet):
    import secrets

    if bullet.process is None:
        pytest.fail("gateway is not running")
    nonce = secrets.token_hex(4)
    offset = bullet.log_size()
    bullet.instruct(
        f"From the allowlisted Feishu account, direct-message the bot:\n"
        f"    ping {nonce} -- reply with exactly: pong-{nonce}"
    )
    try:
        accept = bullet.wait_marker(rf"{re.escape(_ACCEPT_MARKER)}.*msg_type=text", offset=offset)
        sent = bullet.wait_marker(re.escape(_SENT_MARKER), offset=offset)
    except TimeoutError as exc:
        bullet.record("inbound_reply_text", "inconclusive", reason=str(exc))
        pytest.fail(str(exc))
    nonce_echoed = False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not nonce_echoed:
        nonce_echoed = f"pong-{nonce}" in bullet.session_text()
        if not nonce_echoed:
            time.sleep(2)
    status = "passed" if nonce_echoed else "inconclusive"
    bullet.record(
        "inbound_reply_text",
        status,
        inbound_receipt=accept,
        send_receipt=sent,
        nonce_echoed=nonce_echoed,
    )
    if status != "passed":
        pytest.fail("inconclusive: reply delivered but the nonce was not echoed in the session")


def test_attachment_inbound(bullet):
    if bullet.process is None:
        pytest.fail("gateway is not running")
    media_dir = bullet.home / "media" / "feishu"
    before = set(media_dir.glob("*")) if media_dir.is_dir() else set()
    offset = bullet.log_size()
    bullet.instruct("Send the bot one image (any picture, as an image message).")
    try:
        accept = bullet.wait_marker(rf"{re.escape(_ACCEPT_MARKER)}.*msg_type=(image|post)", offset=offset)
    except TimeoutError as exc:
        bullet.record("attachment_inbound", "inconclusive", reason=str(exc))
        pytest.fail(str(exc))
    saved = []
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not saved:
        current = set(media_dir.glob("*")) if media_dir.is_dir() else set()
        saved = sorted(str(p.name) for p in current - before)
        if not saved:
            time.sleep(2)
    status = "passed" if saved else "inconclusive"
    bullet.record("attachment_inbound", status, inbound_receipt=accept, media_saved=bool(saved))
    if status != "passed":
        pytest.fail("inconclusive: image event accepted but no media file was persisted")


def test_media_out(bullet):
    if bullet.process is None:
        pytest.fail("gateway is not running")
    probe = bullet.workspace / "pico-vlf-probe.png"
    probe.write_bytes(_PROBE_PNG)
    offset = bullet.log_size()
    bullet.instruct(
        f"Direct-message the bot exactly:\n    Use the message tool to send me the file {probe} as an attachment."
    )
    try:
        sent = bullet.wait_marker(rf"{re.escape(_SENT_MARKER)} msg_type=image", offset=offset)
    except TimeoutError as exc:
        bullet.record("media_out", "inconclusive", reason=str(exc))
        pytest.fail(str(exc))
    bullet.record("media_out", "passed", send_receipt=sent)


def test_cron_restart_exactly_once(bullet):
    if bullet.process is None:
        pytest.fail("gateway is not running")
    fire_at = datetime.now() + timedelta(seconds=90)
    env = os.environ.copy()
    env["PICO_HOME"] = str(bullet.home)
    added = subprocess.run(
        [
            *bullet._entrypoint(),
            "cron",
            "add",
            "--name",
            "vlf-cron",
            "--message",
            "Reply with exactly: cron-pong",
            "--at",
            fire_at.isoformat(timespec="seconds"),
            "--channel",
            "feishu",
            "--to",
            bullet.operator_id,
            "--yes",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if added.returncode != 0:
        bullet.record(
            "cron_restart_exactly_once",
            "infrastructure_failure",
            reason=f"cron add exited {added.returncode}",
        )
        pytest.fail(f"infrastructure_failure: cron add failed: {added.stdout}{added.stderr}")
    jobs_path = bullet.home / "cron" / "jobs.json"
    assert jobs_path.is_file() and "vlf-cron" in jobs_path.read_text(encoding="utf-8")

    bullet.stop_gateway()
    first_segment_end = bullet.log_size()
    first_segment = bullet.log_text(0, first_segment_end)
    executed_before_restart = first_segment.count(f"{_CRON_EXEC_MARKER} 'vlf-cron'")
    if datetime.now() >= fire_at - timedelta(seconds=15):
        bullet.record(
            "cron_restart_exactly_once",
            "infrastructure_failure",
            reason="gateway shutdown finished too close to the fire time",
        )
        pytest.fail("infrastructure_failure: shutdown overlapped the cron fire window")

    try:
        bullet.start_gateway()
        remaining = (fire_at - datetime.now()).total_seconds()
        executed = bullet.wait_marker(
            rf"{re.escape(_CRON_EXEC_MARKER)} 'vlf-cron'",
            offset=first_segment_end,
            timeout=remaining + _phase_timeout(),
        )
        sent = bullet.wait_marker(re.escape(_SENT_MARKER), offset=first_segment_end)
        bullet.wait_marker(r"Cron: job 'vlf-cron' (completed|failed)", offset=first_segment_end)
    except (RuntimeError, TimeoutError) as exc:
        status = "infrastructure_failure" if "infrastructure" in str(exc) else "inconclusive"
        bullet.record("cron_restart_exactly_once", status, reason=str(exc))
        pytest.fail(str(exc))

    second_segment = bullet.log_text(first_segment_end)
    executed_after_restart = second_segment.count(f"{_CRON_EXEC_MARKER} 'vlf-cron'")
    consumed = False
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not consumed:
        consumed = "vlf-cron" not in jobs_path.read_text(encoding="utf-8")
        if not consumed:
            time.sleep(2)
    exactly_once = executed_before_restart == 0 and executed_after_restart == 1 and consumed
    status = "passed" if exactly_once else "failed"
    bullet.record(
        "cron_restart_exactly_once",
        status,
        executed_before_restart=executed_before_restart,
        executed_after_restart=executed_after_restart,
        job_consumed=consumed,
        websocket_restarted=_BOOT_MARKER in second_segment,
        execution_receipt=executed,
        send_receipt=sent,
    )
    if status != "passed":
        pytest.fail(
            f"cron delivery was not exactly once: before={executed_before_restart} "
            f"after={executed_after_restart} consumed={consumed}"
        )


def test_allowlist_negative_live(bullet):
    if os.environ.get("PICO_LIVE_FEISHU_SECOND_ACTOR") != "1":
        bullet.record("allowlist_negative_live", "skipped", reason="second_account_unavailable")
        pytest.skip("second Feishu account unavailable; deterministic coverage in V-C0")
    if bullet.process is None:
        pytest.fail("gateway is not running")
    offset = bullet.log_size()
    bullet.instruct("From a Feishu account NOT on the allowlist, direct-message the bot.")
    try:
        receipt = bullet.wait_marker(re.escape(_REJECT_MARKER), offset=offset)
    except TimeoutError as exc:
        bullet.record("allowlist_negative_live", "inconclusive", reason=str(exc))
        pytest.fail(str(exc))
    bullet.record("allowlist_negative_live", "passed", reject_receipt=receipt)
