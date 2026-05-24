import json

from pico.evaluation.report_card import build_report_card, write_report_card


def test_report_card_derives_summary_metrics_from_task_results(tmp_path):
    results = [
        {
            "task_id": "core_001",
            "category": "bugfix",
            "strict_pass": True,
            "failure_category": None,
            "evidence_path": "/tmp/evidence/core_001-run1",
            "checks": [
                {"name": "public_test", "passed": True},
                {"name": "report_trace_session_consistency", "passed": True},
            ],
            "report": {"tool_steps": 3, "cost_usd": 0.12},
        },
        {
            "task_id": "core_002",
            "category": "security_fix",
            "strict_pass": False,
            "failure_category": "secret_leak",
            "evidence_path": "/tmp/evidence/core_002-run1",
            "checks": [
                {"name": "public_test", "passed": True},
                {"name": "report_trace_session_consistency", "passed": False},
            ],
            "report": {"tool_steps": 5, "cost_usd": 0.2},
        },
    ]

    card = build_report_card(
        suite="core",
        output_dir=tmp_path,
        pico_commit="abc123",
        started_at="2026-05-21T15:00:00",
        results=results,
    )

    assert card["strict_pass_rate"] == 0.5
    assert card["functional_pass_rate"] == 1.0
    assert card["evidence_consistency_rate"] == 0.5
    assert card["safety_violation_rate"] == 0.5
    assert card["avg_tool_steps"] == 4.0
    assert card["avg_cost_usd"] == 0.16
    assert card["timeout_count"] == 0
    assert card["duration_ms_p50"] == 0.0
    assert card["category_breakdown"]["bugfix"]["strict_passed"] == 1
    assert card["category_breakdown"]["security_fix"]["strict_failed"] == 1
    assert card["failure_taxonomy_table"] == [{"failure_category": "secret_leak", "count": 1}]


def test_write_report_card_writes_json_and_markdown(tmp_path):
    summary = build_report_card(
        suite="core",
        output_dir=tmp_path,
        pico_commit="abc123",
        started_at="2026-05-21T15:00:00",
        results=[],
    )

    write_report_card(summary, tmp_path)

    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["suite"] == "core"
    assert json.loads((tmp_path / "summary_compact.json").read_text(encoding="utf-8"))["suite"] == "core"
    assert "# PicoBench Summary" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_report_card_duration_percentiles_and_timeouts(tmp_path):
    card = build_report_card(
        suite="core",
        output_dir=tmp_path,
        pico_commit="abc123",
        started_at="2026-05-21T15:00:00",
        results=[
            {"task_id": "a", "category": "bugfix", "strict_pass": True, "duration_ms": 100, "checks": [], "report": {}},
            {"task_id": "b", "category": "bugfix", "strict_pass": False, "duration_ms": 200, "failure_category": "timeout", "checks": [], "report": {}},
            {"task_id": "c", "category": "skill", "strict_pass": True, "duration_ms": 300, "checks": [], "report": {}},
        ],
    )

    assert card["timeout_count"] == 1
    assert card["duration_ms_p50"] == 200.0
    assert card["duration_ms_p95"] == 300.0
    assert card["category_breakdown"]["bugfix"]["task_count"] == 2


def test_report_card_excludes_skipped_tasks_from_strict_and_group_denominators(tmp_path):
    card = build_report_card(
        suite="agentic",
        output_dir=tmp_path,
        pico_commit="abc123",
        started_at="2026-05-21T15:00:00",
        results=[
            {
                "task_id": "S07",
                "category": "cli_behavior",
                "strict_pass": True,
                "failure_category": None,
                "checks": [
                    {"name": "public_test", "passed": True},
                    {"name": "report_trace_session_consistency", "passed": True},
                ],
                "report": {},
            },
            {
                "task_id": "R05",
                "category": "tui",
                "strict_pass": False,
                "skipped": True,
                "failure_category": None,
                "checks": [],
                "report": {},
            },
        ],
    )

    assert card["task_count"] == 2
    assert card["skipped"] == 1
    assert card["strict_passed"] == 1
    assert card["strict_failed"] == 0
    assert card["strict_pass_rate"] == 1.0
    assert card["functional_pass_rate"] == 1.0
    assert card["failure_category_counts"] == {}


def test_report_card_marks_delegated_human_gate_evidence_not_applicable(tmp_path):
    card = build_report_card(
        suite="agentic",
        output_dir=tmp_path,
        pico_commit="abc123",
        started_at="2026-05-21T15:00:00",
        results=[
            {
                "task_id": "R01",
                "category": "feature",
                "strict_pass": True,
                "evidence_mode": "delegated_human_gate",
                "checks": [{"name": "v3_human_gate", "passed": True}],
                "report": {},
            }
        ],
    )

    assert card["evidence_mode"] == "delegated_human_gate"
    assert card["evidence_consistency_rate"] == "not_applicable"
    assert "evidence_consistency_rate: not_applicable" in __import__(
        "pico.evaluation.report_card", fromlist=["summary_markdown"]
    ).summary_markdown(card)
