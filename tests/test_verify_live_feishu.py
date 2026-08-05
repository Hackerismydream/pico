from pathlib import Path

from scripts.verify_live_feishu import (
    OPTIONAL_CHECKS,
    REQUIRED_CHECKS,
    aggregate,
    build_criteria,
    excerpt_lines,
    redact_text,
)


def _passed_checks() -> dict[str, dict]:
    return {name: {"status": "passed"} for name in REQUIRED_CHECKS}


def test_redaction_hashes_platform_identifiers() -> None:
    line = "Feishu inbound accepted: ou_abc123def in oc_9f8e7d chat om_11223344"
    redacted = redact_text(line)
    assert "ou_abc123def" not in redacted
    assert "oc_9f8e7d" not in redacted
    assert "om_11223344" not in redacted
    assert "ou_sha:" in redacted and "oc_sha:" in redacted and "om_sha:" in redacted
    assert redact_text(line) == redacted


def test_redaction_strips_secret_env_values(monkeypatch) -> None:
    monkeypatch.setenv("PICO_LIVE_FEISHU_APP_SECRET", "top-secret-value")
    monkeypatch.setenv("PICO_LIVE_API_KEY", "sk-live-key")
    monkeypatch.setenv("PICO_LIVE_FEISHU_APP_ID", "cli_a1b2c3d4e5")
    monkeypatch.setenv("PICO_LIVE_FEISHU_OPERATOR_ID", "ou_operator99")
    text = "secret=top-secret-value key=sk-live-key app=cli_a1b2c3d4e5 op=ou_operator99"
    redacted = redact_text(text)
    assert "top-secret-value" not in redacted
    assert "sk-live-key" not in redacted
    assert "cli_a1b2c3d4e5" not in redacted
    assert "ou_operator99" not in redacted
    assert redacted.count("[redacted-secret]") == 2


def test_excerpt_whitelist_drops_message_bodies() -> None:
    log = "\n".join(
        [
            "2026-01-01 INFO Feishu inbound accepted: message_id=om_1 chat_type=p2p msg_type=text",
            "2026-01-01 DEBUG raw event payload: {'text': 'my private message body'}",
            "2026-01-01 INFO Feishu message sent: msg_type=text message_id=om_2",
            "2026-01-01 INFO Cron: executing job 'vlf-cron' (abc)",
            "2026-01-01 INFO unrelated runtime chatter",
        ]
    )
    lines = excerpt_lines(log)
    assert len(lines) == 3
    assert not any("private message body" in line for line in lines)


def test_aggregate_requires_every_required_phase() -> None:
    checks = _passed_checks()
    assert aggregate(checks, credentials_present=True, required=True) == "passed"
    checks["media_out"] = {"status": "inconclusive"}
    assert aggregate(checks, credentials_present=True, required=True) == "failed"
    del checks["gateway_boot"]
    assert aggregate(checks, credentials_present=True, required=True) == "failed"


def test_aggregate_optional_skip_does_not_block_pass() -> None:
    checks = _passed_checks()
    for name in OPTIONAL_CHECKS:
        checks[name] = {"status": "skipped", "reason": "second_account_unavailable"}
    assert aggregate(checks, credentials_present=True, required=True) == "passed"


def test_aggregate_missing_credentials() -> None:
    assert aggregate({}, credentials_present=False, required=True) == "failed"
    assert aggregate({}, credentials_present=False, required=False) == "skipped"


def test_criteria_upgrade_needs_a_live_pass() -> None:
    checks = _passed_checks()
    criteria = build_criteria(checks)
    assert criteria["allowlist"]["evidence_class"] == "deterministic"
    assert criteria["duplicate_events"]["evidence_class"] == "deterministic"
    checks["allowlist_negative_live"] = {"status": "passed"}
    checks["cron_restart_exactly_once"]["websocket_restarted"] = True
    criteria = build_criteria(checks)
    assert criteria["allowlist"]["evidence_class"] == "both"
    assert criteria["disconnect_reconnect"]["evidence_class"] == "both"


def test_required_checks_match_live_phases() -> None:
    source = (Path(__file__).resolve().parents[1] / "tests" / "integration" / "test_feishu_real_channel.py").read_text(
        encoding="utf-8"
    )
    for name in (*REQUIRED_CHECKS, *OPTIONAL_CHECKS):
        assert f'"{name}"' in source, f"live module records no check named {name}"
