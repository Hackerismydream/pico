import json

from pico.evaluation.provider_failures import (
    normalized_failure_category,
    provider_error_from_evidence,
    provider_failure_category,
)


def test_provider_failure_category_identifies_insufficient_balance():
    assert (
        provider_failure_category(
            {
                "http_status": 402,
                "body_excerpt": '{"error":{"message":"Insufficient Balance"}}',
            }
        )
        == "provider_insufficient_balance"
    )


def test_provider_failure_category_identifies_network_errors():
    assert provider_failure_category({"code": "network_error", "cause_type": "URLError"}) == "provider_network_error"


def test_provider_failure_category_identifies_incomplete_read():
    assert (
        provider_failure_category(
            {
                "code": "model_client_error",
                "cause_type": "IncompleteRead",
                "body_excerpt": "IncompleteRead(723 bytes read)",
            }
        )
        == "provider_network_error"
    )


def test_normalized_failure_category_reads_legacy_model_error_evidence(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "trace.jsonl").write_text(
        json.dumps(
            {
                "event": "model_error",
                "error": {"http_status": 402, "body_excerpt": "Insufficient Balance"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert provider_error_from_evidence(evidence)["http_status"] == 402
    assert normalized_failure_category({"failure_category": "model_error", "evidence_path": str(evidence)}) == "provider_insufficient_balance"
