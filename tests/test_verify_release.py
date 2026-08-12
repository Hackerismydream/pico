"""Tests for the V-R0 release candidate gate driver.

They pin what a release driver can silently get wrong: importing evidence from
another commit, letting a development subset look like a release, and turning a
missing layer into a silent skip. Every subprocess call is monkeypatched; no
real Gate runs here.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

from scripts import verify_release as release

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HEAD = "a" * 40
_OTHER = "b" * 40


def _context(tmp_path: Path, **overrides) -> release.ReleaseContext:
    options = {
        "output_root": tmp_path,
        "head": _HEAD,
        "worktree_clean": True,
        "environ": {},
    }
    options.update(overrides)
    return release.ReleaseContext(**options)


def _completed(command, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


@pytest.fixture
def resolved_executables(monkeypatch):
    monkeypatch.setattr(release.shutil, "which", lambda name: f"/usr/bin/{name}")


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def test_layers_run_in_release_order() -> None:
    assert release.LAYER_NAMES == (
        "v_d0",
        "v_t0",
        "v_p0",
        "host_gate",
        "v_lp",
        "v_c0_s0",
        "v_lf",
        "memory_continuity",
        "v_te0",
        "v_e0",
        "deps_audit",
        "assets",
        "evolution",
    )
    assert set(release.HANDLERS) == set(release.LAYER_NAMES)


def test_every_layer_declares_an_evidence_class() -> None:
    assert {spec.evidence_class for spec in release.LAYERS} <= {
        release.DETERMINISTIC,
        release.PACKAGE,
        release.LIVE,
        release.AUDIT,
    }
    assert release._LAYER_BY_NAME["v_lf"].evidence_class == release.LIVE
    assert release._LAYER_BY_NAME["memory_continuity"].evidence_class == release.PACKAGE
    assert release._LAYER_BY_NAME["deps_audit"].evidence_class == release.AUDIT


def test_selection_defaults_to_every_layer_in_order() -> None:
    assert release.select_layers(None) == release.LAYER_NAMES


def test_memory_continuity_stays_blocked_until_myna_is_released(
    tmp_path: Path,
) -> None:
    spec = release._LAYER_BY_NAME["memory_continuity"]

    record = release.run_memory_continuity(_context(tmp_path), spec)

    assert record["status"] == release.INCONCLUSIVE
    assert record["gaps"] == [
        {
            "gap": "myna_release_unavailable",
            "detail": (
                "the compatible myna-memory distribution is not available from a "
                "formal artifact source, so V-R0 cannot reproduce the installed "
                "composition from publishable dependencies"
            ),
        }
    ]


def test_selection_subset_keeps_canonical_order() -> None:
    assert release.select_layers("assets, v_d0") == ("v_d0", "assets")


def test_unknown_or_empty_selection_is_rejected() -> None:
    with pytest.raises(ValueError):
        release.select_layers("v_zz0")
    with pytest.raises(ValueError):
        release.select_layers(" , ")


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def test_clean_exit_passes_and_dirty_exit_fails() -> None:
    assert release.classify_exit(0, "everything is green") == release.PASSED
    assert release.classify_exit(1, "1 failed") == release.FAILED


def test_provider_and_infrastructure_failures_stay_separate() -> None:
    assert release.classify_exit(1, "V-LP provider_failure: upstream 503") == release.PROVIDER_FAILURE
    assert release.classify_exit(2, "infrastructure_failure: no runner") == release.INFRASTRUCTURE_FAILURE
    assert release.classify_exit(1, "inconclusive: provider unavailable") == release.INCONCLUSIVE
    assert release.classify_exit(1, "E   Failed: infrastructure_failure: uv executable not found") == (
        release.INFRASTRUCTURE_FAILURE
    )


def test_a_test_id_naming_a_marker_word_stays_a_product_failure() -> None:
    """The retained and Evolver suites own test ids that spell the marker words."""
    output = (
        "FAILED tests/test_evolver_gates.py::TestConfirmGate::test_provider_failure_refuses_promotion\n"
        "FAILED tests/test_evolver_gates.py::TestProbeGate::test_zero_attempt_measurement_is_inconclusive\n"
        "FAILED tests/test_evolver_scoring.py::test_provider_failure_is_not_reclassified_as_infrastructure\n"
        "FAILED tests/test_evolver_activation_artifacts.py::test_outcome[inconclusive]\n"
        "3 failed, 3545 passed\n"
    )
    assert release.classify_exit(1, output) == release.FAILED
    assert release.classify_exit(1, "E   assert verdict is EvaluationVerdict.inconclusive") == release.FAILED
    assert release.classify_exit(1, 'E   assert record["status"] == "inconclusive"') == release.FAILED


def test_a_timeout_is_infrastructure_not_a_product_failure() -> None:
    assert release.classify_exit(None, "", outcome="timeout") == release.INFRASTRUCTURE_FAILURE
    assert release.classify_exit(None, "", outcome="executable_missing") == release.INFRASTRUCTURE_FAILURE


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def test_report_commit_reads_every_sub_report_shape() -> None:
    assert release.report_commit({"source_sha": _HEAD}) == _HEAD
    assert release.report_commit({"commit": _HEAD}) == _HEAD
    assert release.report_commit({"source": {"commit": _HEAD}}) == _HEAD
    assert release.report_commit({"status": "passed"}) is None


def test_a_report_from_this_commit_binds() -> None:
    gaps, binding = release.bind_report(
        {"source_sha": _HEAD}, head=_HEAD, produced_at=time.time(), layer_started=time.time() - 5
    )
    assert gaps == ()
    assert binding["commit_binding"] == "recorded"


def test_a_report_from_another_commit_is_refused() -> None:
    gaps, binding = release.bind_report(
        {"source_sha": _OTHER}, head=_HEAD, produced_at=time.time(), layer_started=time.time() - 5
    )
    assert [gap["gap"] for gap in gaps] == ["report_stale_commit"]
    assert binding["report_commit"] == _OTHER


def test_a_report_older_than_the_layer_is_refused() -> None:
    started = time.time()
    gaps, _binding = release.bind_report(
        {"status": "passed"}, head=_HEAD, produced_at=started - 600, layer_started=started
    )
    assert [gap["gap"] for gap in gaps] == ["report_stale_artifact"]


def test_a_missing_report_is_a_named_gap() -> None:
    gaps, binding = release.bind_report(None, head=_HEAD, produced_at=None, layer_started=time.time())
    assert [gap["gap"] for gap in gaps] == ["report_missing"]
    assert binding["commit_binding"] == "none"


def test_a_layer_that_cannot_bind_its_report_never_passes() -> None:
    assert release.resolve_layer_status(release.PASSED, ()) == release.PASSED
    assert release.resolve_layer_status(release.PASSED, [{"gap": "report_stale_commit"}]) == release.FAILED
    assert release.resolve_layer_status(release.FAILED, ()) == release.FAILED


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def _records(**statuses) -> list[dict]:
    return [{"layer": name, "status": statuses.get(name, release.PASSED), "gaps": []} for name in release.LAYER_NAMES]


def test_a_complete_run_passes_only_when_every_layer_passed() -> None:
    assert release.overall_status(_records(), release_eligible=True) == release.PASSED
    assert release.overall_status(_records(v_lf=release.FAILED), release_eligible=True) == release.FAILED


def test_a_subset_run_cannot_report_passed() -> None:
    records = [{"layer": "assets", "status": release.PASSED, "gaps": []}] + [
        {"layer": name, "status": release.SKIPPED, "gaps": []} for name in release.LAYER_NAMES if name != "assets"
    ]
    assert release.overall_status(records, release_eligible=False) == release.FAILED


def test_the_most_severe_result_names_the_run() -> None:
    assert release.overall_status(_records(v_lp=release.PROVIDER_FAILURE), release_eligible=True) == (
        release.PROVIDER_FAILURE
    )
    assert (
        release.overall_status(_records(v_lp=release.PROVIDER_FAILURE, v_lf=release.FAILED), release_eligible=True)
        == release.FAILED
    )
    assert release.overall_status(_records(evolution=release.INCONCLUSIVE), release_eligible=True) == (
        release.INCONCLUSIVE
    )


def test_report_carries_the_schema_commit_and_gap_layers() -> None:
    records = _records()
    records[0]["gaps"] = [{"gap": "report_missing", "detail": "no report"}]
    report = release.build_report(
        records,
        head=_HEAD,
        worktree_clean=True,
        selection=release.LAYER_NAMES,
        handoff={"wheel": "/tmp/pico.whl"},
        completed_at="2026-07-26T00:00:00+00:00",
    )
    assert report["schema"] == "pico.release.evidence.v1"
    assert report["gate"] == "V-R0"
    assert report["commit"] == _HEAD
    assert report["rerun"] == "make verify-release"
    assert report["selection"] == {"complete": True, "requested": list(release.LAYER_NAMES)}
    assert report["gaps"] == [{"layer": "v_d0", "gap": "report_missing", "detail": "no report"}]
    assert report["status"] == release.FAILED


def test_a_dirty_checkout_cannot_describe_a_release_commit() -> None:
    report = release.build_report(
        _records(),
        head=_HEAD,
        worktree_clean=False,
        selection=release.LAYER_NAMES,
        handoff=None,
        completed_at="2026-07-26T00:00:00+00:00",
    )
    assert report["status"] == release.FAILED
    assert [gap["gap"] for gap in report["gaps"]] == ["worktree_dirty"]


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def test_missing_live_credentials_are_listed_by_name() -> None:
    assert release.missing_environment(release._LIVE_FEISHU_ENV, {}) == release._LIVE_FEISHU_ENV
    assert release.missing_environment(release._LIVE_PROVIDER_ENV, {"PICO_LIVE_API_KEY": "x"}) == ()


def test_absent_small_real_inputs_are_named(tmp_path: Path) -> None:
    assert release.missing_small_real_inputs(tmp_path) == (
        "scripts/setup_small_real_subject.py",
        "benchmarks/evolver/small_real.yaml",
    )
    for name in release.missing_small_real_inputs(tmp_path):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    assert release.missing_small_real_inputs(tmp_path) == ()


def test_the_evolution_layer_reports_the_missing_files_gap(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(release, "_SMALL_REAL_CONFIG", "benchmarks/evolver/absent.yaml")
    record = release.run_evolution(_context(tmp_path), release._LAYER_BY_NAME["evolution"])
    assert record["status"] == release.INCONCLUSIVE
    assert [gap["gap"] for gap in record["gaps"]] == ["small_real_files_missing"]
    assert record["command"] == []


def test_a_live_layer_without_credentials_is_a_failed_required_layer(tmp_path: Path) -> None:
    record = release.run_v_lf(_context(tmp_path), release._LAYER_BY_NAME["v_lf"])
    assert record["status"] == release.FAILED
    assert [gap["gap"] for gap in record["gaps"]] == ["feishu_credentials_missing"]


def test_a_layer_without_the_distribution_handoff_is_inconclusive(tmp_path: Path) -> None:
    record = release.run_host_gate(_context(tmp_path), release._LAYER_BY_NAME["host_gate"])
    assert record["status"] == release.INCONCLUSIVE
    assert [gap["gap"] for gap in record["gaps"]] == ["distribution_handoff_missing"]


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


_PIP_AUDIT = {
    "dependencies": [
        {"name": "Click", "version": "8.1.8", "vulns": [{"id": "GHSA-47fr-3ffg-hgmw", "aliases": ["CVE-2026-0001"]}]},
        {"name": "rich", "version": "14.0.0", "vulns": []},
    ]
}
_NPM_AUDIT = {
    "vulnerabilities": {
        "brace-expansion": {
            "name": "brace-expansion",
            "severity": "high",
            "via": [{"url": "https://github.com/advisories/GHSA-3jxr-9vmj-r5cp", "severity": "high"}],
        },
        "minimatch": {"name": "minimatch", "severity": "high", "via": ["brace-expansion"]},
        "tmp": {"name": "tmp", "severity": "low", "via": ["brace-expansion"]},
    }
}


def test_pip_audit_findings_carry_no_severity() -> None:
    findings = release.parse_pip_audit(_PIP_AUDIT)
    assert len(findings) == 1
    assert findings[0].package == "click"
    assert findings[0].severity is None
    assert "GHSA-47FR-3FFG-HGMW" in findings[0].advisory_ids
    assert findings[0].surface == release._ENVIRONMENT_SURFACE


def test_npm_audit_findings_carry_severity_and_advisory_ids() -> None:
    findings = release.parse_npm_audit(_NPM_AUDIT, ecosystem="npm-ui-tui", surface=release._DEVELOPMENT_SURFACE)
    by_package = {finding.package: finding for finding in findings}
    assert by_package["brace-expansion"].severity == "high"
    assert by_package["brace-expansion"].advisory_ids == ("GHSA-3JXR-9VMJ-R5CP",)
    assert by_package["brace-expansion"].via_packages == ()
    assert by_package["tmp"].advisory_ids == ()
    assert by_package["tmp"].via_packages == ("brace-expansion",)


def test_production_surface_wins_over_the_development_audit() -> None:
    full = release.parse_npm_audit(_NPM_AUDIT, ecosystem="npm-ui-tui", surface=release._DEVELOPMENT_SURFACE)
    production = release.parse_npm_audit(
        {"vulnerabilities": {"tmp": {"name": "tmp", "severity": "low", "via": []}}},
        ecosystem="npm-ui-tui",
        surface=release._PRODUCTION_SURFACE,
    )
    surfaces = {finding.package: finding.surface for finding in release.split_npm_surfaces(full, production)}
    assert surfaces == {
        "tmp": release._PRODUCTION_SURFACE,
        "brace-expansion": release._DEVELOPMENT_SURFACE,
        "minimatch": release._DEVELOPMENT_SURFACE,
    }


def _entry(**overrides) -> release.LedgerEntry:
    options = {
        "id": "DEP-NPM-BRACE-EXPANSION",
        "ecosystem": "npm-ui-tui",
        "package": "brace-expansion",
        "advisory_ids": frozenset({"GHSA-3JXR-9VMJ-R5CP"}),
        "disposition": release._ACTIVE_EXCEPTION,
        "expiry": "after-v1",
    }
    options.update(overrides)
    return release.LedgerEntry(**options)


def _finding(**overrides) -> release.Finding:
    options = {
        "ecosystem": "npm-ui-tui",
        "package": "brace-expansion",
        "severity": "high",
        "advisory_ids": ("GHSA-3JXR-9VMJ-R5CP",),
        "surface": release._DEVELOPMENT_SURFACE,
    }
    options.update(overrides)
    return release.Finding(**options)


def test_an_unledgered_high_finding_blocks_the_layer() -> None:
    reconciled = release.reconcile_findings((_finding(),), (), block_critical_or_high=True)
    assert reconciled[0]["blocking"] is True
    assert reconciled[0]["disposition"] == "unledgered"
    assert [gap["gap"] for gap in release.dependency_gaps(reconciled)] == ["dependency_finding_blocking"]


def test_an_active_exception_waives_a_development_finding() -> None:
    reconciled = release.reconcile_findings((_finding(),), (_entry(),), block_critical_or_high=True)
    assert reconciled[0]["blocking"] is False
    assert reconciled[0]["disposition"] == "ledgered"
    assert reconciled[0]["ledger_id"] == "DEP-NPM-BRACE-EXPANSION"
    assert release.dependency_gaps(reconciled) == ()


def test_an_exception_that_expires_before_v_r0_cannot_waive_inside_v_r0() -> None:
    reconciled = release.reconcile_findings((_finding(),), (_entry(expiry="before-v-r0"),), block_critical_or_high=True)
    assert reconciled[0]["blocking"] is True
    assert reconciled[0]["disposition"] == "ledger_entry_closed"


def test_a_remediated_entry_does_not_waive_a_returning_finding() -> None:
    reconciled = release.reconcile_findings(
        (_finding(),), (_entry(disposition="remediated"),), block_critical_or_high=True
    )
    assert reconciled[0]["blocking"] is True
    assert reconciled[0]["disposition"] == "ledger_entry_closed"


def test_a_production_high_finding_is_blocked_by_policy_even_when_ledgered() -> None:
    reconciled = release.reconcile_findings(
        (_finding(surface=release._PRODUCTION_SURFACE),), (_entry(),), block_critical_or_high=True
    )
    assert reconciled[0]["blocking"] is True
    assert reconciled[0]["disposition"] == "policy_blocked"


def test_a_low_severity_finding_is_below_the_release_threshold() -> None:
    reconciled = release.reconcile_findings((_finding(severity="low"),), (), block_critical_or_high=True)
    assert reconciled[0]["blocking"] is False
    assert reconciled[0]["disposition"] == "below_release_threshold"


def test_a_dependent_inherits_its_root_advisory_instead_of_a_second_gap() -> None:
    """npm repeats one advisory on every dependent; the ledger records it once."""
    findings = release.parse_npm_audit(_NPM_AUDIT, ecosystem="npm-ui-tui", surface=release._DEVELOPMENT_SURFACE)
    reconciled = {row["package"]: row for row in release.reconcile_findings(findings, (), block_critical_or_high=True)}
    assert reconciled["brace-expansion"]["blocking"] is True
    assert reconciled["brace-expansion"]["disposition"] == "unledgered"
    assert reconciled["minimatch"]["blocking"] is False
    assert reconciled["minimatch"]["disposition"] == "transitive"
    assert reconciled["minimatch"]["via"] == ["brace-expansion"]


def test_a_dependent_of_an_unreported_package_still_blocks() -> None:
    orphan = _finding(package="minimatch", advisory_ids=(), via_packages=("brace-expansion",))
    reconciled = release.reconcile_findings((orphan,), (), block_critical_or_high=True)
    assert reconciled[0]["blocking"] is True
    assert reconciled[0]["disposition"] == "unledgered"


def test_a_severity_unknown_python_finding_blocks_unless_ledgered() -> None:
    finding = _finding(ecosystem="python", package="click", severity=None, advisory_ids=("GHSA-47FR-3FFG-HGMW",))
    assert release.reconcile_findings((finding,), (), block_critical_or_high=True)[0]["blocking"] is True
    entry = _entry(
        id="DEP-PY-CLICK", ecosystem="python", package="click", advisory_ids=frozenset({"GHSA-47FR-3FFG-HGMW"})
    )
    assert release.reconcile_findings((finding,), (entry,), block_critical_or_high=True)[0]["blocking"] is False


def test_the_repository_ledger_parses_and_blocks_critical_or_high() -> None:
    payload = tomllib.loads((_REPO_ROOT / release.LEDGER_PATH).read_text(encoding="utf-8"))
    entries, block_critical_or_high = release.load_ledger(payload)
    assert block_critical_or_high is True
    assert entries == ()


# --------------------------------------------------------------------------

# --------------------------------------------------------------------------


def test_a_gate_layer_record_has_the_documented_shape(tmp_path: Path, monkeypatch, resolved_executables) -> None:
    calls: list[list[str]] = []
    environments: list[dict | None] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        environments.append(kwargs.get("env"))
        if command[1] == "diff":
            return _completed(command, 0, "docs/specs/release-candidate-gate.md\n")
        return _completed(command, 0, "V-R0 layer output\n")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    record = release.run_assets(_context(tmp_path), release._LAYER_BY_NAME["assets"])

    assert calls[-1] == ["/usr/bin/make", "check-large-files"]
    assert environments[-1]["COMMIT_RANGE"] == "origin/main..HEAD"
    assert record["commit_range"] == "origin/main..HEAD"
    assert record["changed_paths"] == 1
    assert record["layer"] == "assets"
    assert record["gate"] == "asset gate"
    assert record["status"] == release.PASSED
    assert record["exit_code"] == 0
    assert record["command"] == [["/usr/bin/make", "check-large-files"]]
    assert record["evidence_class"] == release.DETERMINISTIC
    assert record["gaps"] == []
    assert "report_path" not in record
    log_path = tmp_path / "logs" / "assets.log"
    assert record["log"] == log_path.name
    assert len(record["log_sha256"]) == 64
    assert "V-R0 layer output" in log_path.read_text(encoding="utf-8")


def test_a_layer_imports_a_sub_report_written_at_this_commit(tmp_path: Path, monkeypatch, resolved_executables) -> None:
    report_path = tmp_path / "channels-report.json"

    def fake_run(command, **kwargs):
        report_path.write_text(json.dumps({"commit": _HEAD, "status": "passed"}), encoding="utf-8")
        return _completed(command, 0, "V-C0 passed\n")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    record = release._gate_layer(
        _context(tmp_path), release._LAYER_BY_NAME["v_c0_s0"], ["make", "verify-channels"], report_path=report_path
    )
    assert record["status"] == release.PASSED
    assert record["report_path"] == str(report_path)
    assert len(record["report_sha256"]) == 64
    assert record["commit_binding"] == "recorded"


def test_a_layer_refuses_a_sub_report_from_another_commit(tmp_path: Path, monkeypatch, resolved_executables) -> None:
    report_path = tmp_path / "channels-report.json"

    def fake_run(command, **kwargs):
        report_path.write_text(json.dumps({"commit": _OTHER, "status": "passed"}), encoding="utf-8")
        return _completed(command, 0, "V-C0 passed\n")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    record = release._gate_layer(
        _context(tmp_path), release._LAYER_BY_NAME["v_c0_s0"], ["make", "verify-channels"], report_path=report_path
    )
    assert record["status"] == release.FAILED
    assert [gap["gap"] for gap in record["gaps"]] == ["report_stale_commit"]


def test_a_layer_refuses_a_sub_report_left_by_an_earlier_run(tmp_path: Path, monkeypatch, resolved_executables) -> None:
    report_path = tmp_path / "channels-report.json"
    report_path.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    stale = time.time() - 86400
    os.utime(report_path, (stale, stale))

    monkeypatch.setattr(release.subprocess, "run", lambda command, **kwargs: _completed(command, 0, "V-C0 passed\n"))
    record = release._gate_layer(
        _context(tmp_path), release._LAYER_BY_NAME["v_c0_s0"], ["make", "verify-channels"], report_path=report_path
    )
    assert record["status"] == release.FAILED
    assert [gap["gap"] for gap in record["gaps"]] == ["report_stale_artifact"]


def test_a_subset_run_names_every_layer_it_did_not_run(tmp_path: Path, monkeypatch, resolved_executables) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if command[1] == "diff":
            return _completed(command, 0, "docs/dev.md\n")
        return _completed(command, 0, "ok\n")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    context = _context(tmp_path)
    records = release.run_layers(context, ("assets",))
    report = release.build_report(
        records,
        head=context.head,
        worktree_clean=True,
        selection=("assets",),
        handoff=None,
        completed_at="2026-07-26T00:00:00+00:00",
    )

    assert calls == [
        ["/usr/bin/git", "diff", "--name-only", "--diff-filter=AM", "origin/main..HEAD"],
        ["/usr/bin/make", "check-large-files"],
    ]
    assert len(records) == len(release.LAYER_NAMES)
    assert report["status"] == release.FAILED
    assert report["selection"] == {"complete": False, "requested": ["assets"]}
    not_run = {gap["layer"] for gap in report["gaps"] if gap["gap"] == "layer_not_run"}
    assert not_run == set(release.LAYER_NAMES) - {"assets"}


def test_the_dependency_layer_blocks_on_an_unledgered_finding(
    tmp_path: Path, monkeypatch, resolved_executables
) -> None:
    payloads = {
        "pip_audit": json.dumps({"dependencies": []}),
        "npm_audit": json.dumps(
            {
                "vulnerabilities": {
                    "left-pad": {
                        "name": "left-pad",
                        "severity": "critical",
                        "via": [{"url": "https://github.com/advisories/GHSA-1111-2222-3333"}],
                    }
                }
            }
        ),
        "npm_audit_production": json.dumps({"vulnerabilities": {}}),
    }

    def fake_run(command, **kwargs):
        if "pip_audit" in command:
            return _completed(command, 0, payloads["pip_audit"])
        if "--omit=dev" in command:
            return _completed(command, 0, payloads["npm_audit_production"])
        return _completed(command, 1, payloads["npm_audit"])

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    record = release.run_deps_audit(_context(tmp_path), release._LAYER_BY_NAME["deps_audit"])

    assert record["status"] == release.FAILED
    assert record["blocking_findings"] == 1
    assert [gap["gap"] for gap in record["gaps"]] == ["dependency_finding_blocking"]
    payload = json.loads(Path(record["report_path"]).read_text(encoding="utf-8"))
    assert payload["findings"][0]["package"] == "left-pad"
    assert payload["commit"] == _HEAD


def test_the_dependency_layer_reports_unparseable_audit_output(
    tmp_path: Path, monkeypatch, resolved_executables
) -> None:
    monkeypatch.setattr(release.subprocess, "run", lambda command, **kwargs: _completed(command, 1, "not json"))
    record = release.run_deps_audit(_context(tmp_path), release._LAYER_BY_NAME["deps_audit"])
    assert record["status"] == release.INFRASTRUCTURE_FAILURE
    assert {gap["gap"] for gap in record["gaps"]} == {"dependency_audit_unreadable"}
