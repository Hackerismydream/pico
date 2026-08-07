#!/usr/bin/env python3
"""V-R0: assemble every release layer into one report bound to one commit.

The driver runs the retained, TUI, distribution, host, live, evidence, audit,
asset, and Evolution Run layers in release order, imports a sub-report only when
that report was recorded at the commit under test, and names what is missing
instead of skipping it. Contract: docs/specs/release-candidate-gate.md.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "pico.release.evidence.v1"
GATE = "V-R0"
RERUN = "make verify-release"
REPORT_FILENAME = "release-report.json"
DEPENDENCY_REPORT_FILENAME = "dependency-audit.json"
LEDGER_PATH = Path("docs/baselines/exception-ledger.toml")

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
INCONCLUSIVE = "inconclusive"
PROVIDER_FAILURE = "provider_failure"
INFRASTRUCTURE_FAILURE = "infrastructure_failure"

DETERMINISTIC = "deterministic"
PACKAGE = "package"
LIVE = "live"
AUDIT = "audit"

_SEVERITY_ORDER = (FAILED, PROVIDER_FAILURE, INFRASTRUCTURE_FAILURE, INCONCLUSIVE)
_OUTPUT_MARKERS = (PROVIDER_FAILURE, INFRASTRUCTURE_FAILURE, INCONCLUSIVE)
# A layer names a non-default status as "<status>: <detail>". Matching the bare
# word anywhere in a suite's output would let a test id such as
# test_provider_failure_refuses_promotion rewrite a deterministic regression
# into an upstream outage.
_MARKER_PATTERNS = {status: re.compile(rf"\b{status}:") for status in _OUTPUT_MARKERS}

# A report file older than the layer that claims it was produced by a previous
# run. Filesystems with coarse timestamps need a small tolerance.
_MTIME_TOLERANCE_SECONDS = 2.0

_DISTRIBUTION_ENTRYPOINT = "pico"
_DISTRIBUTION_EXTRAS = "base,channel-feishu,channel-qq,channel-wecom,channels,sandbox"

_LIVE_PROVIDER_ENV = ("PICO_LIVE_API_KEY",)
_LIVE_FEISHU_ENV = (
    "PICO_LIVE_API_KEY",
    "PICO_LIVE_FEISHU_APP_ID",
    "PICO_LIVE_FEISHU_APP_SECRET",
    "PICO_LIVE_FEISHU_OPERATOR_ID",
)

_ASSET_RANGE_ENV = "COMMIT_RANGE"
_ASSET_DEFAULT_RANGE = "origin/main..HEAD"

_SMALL_REAL_SETUP = "scripts/setup_small_real_subject.py"
_SMALL_REAL_CONFIG = "benchmarks/evolver/small_real.yaml"
_EVOLUTION_INTERRUPT_SECONDS = 180.0
_EVOLUTION_SHUTDOWN_SECONDS = 300.0

_BLOCKING_SEVERITIES = frozenset({"critical", "high"})
_ACTIVE_EXCEPTION = "temporary-reachability-exception"
# An exception that expires before V-R0 cannot waive a finding inside a V-R0
# run: honoring it would silence exactly the advisory it asked to re-evaluate.
_EXPIRED_AT_RELEASE = frozenset({"before-v-r0"})
_ADVISORY_PATTERN = re.compile(r"GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4}", re.IGNORECASE)
_PYTHON_ECOSYSTEM = "python"
_NPM_UI_TUI_ECOSYSTEM = "npm-ui-tui"
_PRODUCTION_SURFACE = "production"
_DEVELOPMENT_SURFACE = "development"
_ENVIRONMENT_SURFACE = "environment"
# An audit that could not run still exits non-zero with valid JSON, so the
# result key is what separates a completed audit from an error payload such as
# npm's {"error": {"code": "ENOLOCK"}}.
_AUDIT_RESULT_KEY = {
    "pip_audit": "dependencies",
    "npm_audit": "vulnerabilities",
    "npm_audit_production": "vulnerabilities",
}


@dataclass(frozen=True)
class LayerSpec:
    name: str
    gate: str
    evidence_class: str
    timeout: float


LAYERS: tuple[LayerSpec, ...] = (
    LayerSpec("v_d0", "V-D0", DETERMINISTIC, 5400),
    LayerSpec("v_t0", "V-T0", DETERMINISTIC, 2400),
    LayerSpec("v_p0", "V-P0", PACKAGE, 7200),
    LayerSpec("host_gate", "host gate", PACKAGE, 3600),
    LayerSpec("v_lp", "V-LP", LIVE, 2400),
    LayerSpec("v_c0_s0", "V-C0/V-S0", DETERMINISTIC, 2400),
    LayerSpec("v_lf", "V-LF", LIVE, 5400),
    LayerSpec("memory_continuity", "Myna installed composition", PACKAGE, 0),
    LayerSpec("v_te0", "V-TE0", DETERMINISTIC, 1200),
    LayerSpec("v_e0", "V-E0", DETERMINISTIC, 2400),
    LayerSpec("deps_audit", "dependency audit", AUDIT, 2400),
    LayerSpec("assets", "asset gate", DETERMINISTIC, 600),
    LayerSpec("evolution", "small real Evolution Run", LIVE, 21600),
)
LAYER_NAMES: tuple[str, ...] = tuple(spec.name for spec in LAYERS)
_LAYER_BY_NAME = {spec.name: spec for spec in LAYERS}


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    outcome: str
    elapsed_seconds: float = 0.0

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@dataclass
class ReleaseContext:
    output_root: Path
    head: str
    worktree_clean: bool
    environ: dict[str, str]
    handoff: dict[str, Any] | None = None
    distribution_root: Path | None = None
    logs: Path = field(init=False)

    def __post_init__(self) -> None:
        self.logs = self.output_root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# selection, classification, and binding: the pure core
# --------------------------------------------------------------------------


def select_layers(requested: str | None) -> tuple[str, ...]:
    """Resolve a comma-separated subset to canonical release order."""
    if requested is None:
        return LAYER_NAMES
    names = [part.strip() for part in requested.split(",") if part.strip()]
    if not names:
        raise ValueError("--layers must name at least one layer")
    unknown = sorted(set(names) - set(LAYER_NAMES))
    if unknown:
        raise ValueError(f"unknown layers: {unknown}; known layers: {list(LAYER_NAMES)}")
    return tuple(name for name in LAYER_NAMES if name in set(names))


def classify_exit(exit_code: int | None, output: str, *, outcome: str = "completed") -> str:
    """Map one command result onto the shared status vocabulary."""
    if outcome != "completed":
        return INFRASTRUCTURE_FAILURE
    if exit_code == 0:
        return PASSED
    lowered = output.lower()
    for status in _OUTPUT_MARKERS:
        if _MARKER_PATTERNS[status].search(lowered):
            return status
    return FAILED


def report_commit(payload: dict[str, Any]) -> str | None:
    """Read the commit a sub-report recorded, across the report shapes in use."""
    for key in ("source_sha", "commit"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    source = payload.get("source")
    if isinstance(source, dict):
        value = source.get("commit")
        if isinstance(value, str) and value:
            return value
    return None


def bind_report(
    payload: dict[str, Any] | None,
    *,
    head: str,
    produced_at: float | None,
    layer_started: float,
) -> tuple[tuple[dict[str, str], ...], dict[str, Any]]:
    """Bind a sub-report to the commit under test.

    Returns the gaps that block the import and the binding metadata. A report
    recorded at another commit, or produced before this layer ran, is stale
    evidence: it is named, never imported as a pass.
    """
    if payload is None:
        return (
            ({"gap": "report_missing", "detail": "the layer produced no readable report"},),
            {"commit_binding": "none"},
        )
    recorded = report_commit(payload)
    if recorded is not None and recorded != head:
        return (
            (
                {
                    "gap": "report_stale_commit",
                    "detail": f"report records commit {recorded}, the run is bound to {head}",
                },
            ),
            {"commit_binding": "recorded", "report_commit": recorded},
        )
    if produced_at is not None and produced_at < layer_started - _MTIME_TOLERANCE_SECONDS:
        return (
            (
                {
                    "gap": "report_stale_artifact",
                    "detail": "report predates this layer, so it belongs to an earlier run",
                },
            ),
            {"commit_binding": "none", "report_commit": recorded},
        )
    return (), {"commit_binding": "recorded" if recorded else "run", "report_commit": recorded}


def resolve_layer_status(status: str, gaps: tuple[dict[str, str], ...] | list[dict[str, str]]) -> str:
    """A layer that cannot bind its own evidence never reports a pass."""
    if status == PASSED and gaps:
        return FAILED
    return status


def overall_status(records: list[dict[str, Any]], *, release_eligible: bool) -> str:
    """Only a release-eligible run whose every layer passed is a release result.

    A run is release-eligible when it selected every layer and named no gap.
    """
    statuses = {record["status"] for record in records}
    if release_eligible and statuses == {PASSED}:
        return PASSED
    for candidate in _SEVERITY_ORDER:
        if candidate in statuses:
            return candidate
    return FAILED


def build_report(
    records: list[dict[str, Any]],
    *,
    head: str,
    worktree_clean: bool,
    selection: tuple[str, ...],
    handoff: dict[str, Any] | None,
    completed_at: str,
) -> dict[str, Any]:
    complete = tuple(selection) == LAYER_NAMES
    gaps = [
        {"layer": record["layer"], **gap}
        for record in records
        for gap in record.get("gaps", [])
        if isinstance(gap, dict)
    ]
    if not worktree_clean:
        gaps.append(
            {
                "layer": "run",
                "gap": "worktree_dirty",
                "detail": "release evidence must describe a commit; the checkout has uncommitted changes",
            }
        )
    status = overall_status(records, release_eligible=complete and not gaps)
    return {
        "commit": head,
        "completed_at": completed_at,
        "gaps": gaps,
        "gate": GATE,
        "handoff": handoff,
        "layers": records,
        "rerun": RERUN,
        "schema": SCHEMA,
        "selection": {"complete": complete, "requested": list(selection)},
        "status": status,
        "worktree_clean": worktree_clean,
    }


def missing_environment(names: tuple[str, ...], environ: dict[str, str]) -> tuple[str, ...]:
    return tuple(name for name in names if not environ.get(name))


def missing_small_real_inputs(root: Path) -> tuple[str, ...]:
    """The setup script and run spec a parallel change owns; absence is a gap."""
    return tuple(name for name in (_SMALL_REAL_SETUP, _SMALL_REAL_CONFIG) if not (root / name).is_file())


# --------------------------------------------------------------------------
# dependency audit reconciliation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    ecosystem: str
    package: str
    advisory_ids: frozenset[str]
    disposition: str
    expiry: str

    def waives(self) -> bool:
        return self.disposition == _ACTIVE_EXCEPTION and self.expiry not in _EXPIRED_AT_RELEASE


@dataclass(frozen=True)
class Finding:
    ecosystem: str
    package: str
    severity: str | None
    advisory_ids: tuple[str, ...]
    surface: str
    via_packages: tuple[str, ...] = ()


def load_ledger(payload: dict[str, Any]) -> tuple[tuple[LedgerEntry, ...], bool]:
    entries = tuple(
        LedgerEntry(
            id=str(row.get("id", "")),
            ecosystem=str(row.get("ecosystem", "")),
            package=str(row.get("package", "")).lower(),
            advisory_ids=frozenset(str(value).upper() for value in row.get("advisory_ids", [])),
            disposition=str(row.get("disposition", "")),
            expiry=str(row.get("expiry", "")),
        )
        for row in payload.get("dependency", [])
    )
    policy = payload.get("policy", {})
    return entries, bool(policy.get("release_blocks_critical_or_high", True))


def parse_pip_audit(payload: dict[str, Any]) -> tuple[Finding, ...]:
    """pip-audit reports no severity, so every finding stays severity-unknown."""
    findings: list[Finding] = []
    for dependency in payload.get("dependencies", []):
        package = str(dependency.get("name", "")).lower()
        for vulnerability in dependency.get("vulns", []):
            ids = [str(vulnerability.get("id", ""))] + [str(alias) for alias in vulnerability.get("aliases", [])]
            findings.append(
                Finding(
                    ecosystem=_PYTHON_ECOSYSTEM,
                    package=package,
                    severity=None,
                    advisory_ids=tuple(sorted({value.upper() for value in ids if value})),
                    surface=_ENVIRONMENT_SURFACE,
                )
            )
    return tuple(findings)


def parse_npm_audit(payload: dict[str, Any], *, ecosystem: str, surface: str) -> tuple[Finding, ...]:
    """npm names an advisory on the affected package and lists every dependent.

    A dependent carries package names in ``via`` and no advisory of its own,
    which is what distinguishes a transitive entry from a direct finding.
    """
    findings: list[Finding] = []
    for name, entry in sorted(payload.get("vulnerabilities", {}).items()):
        if not isinstance(entry, dict):
            continue
        advisories: set[str] = set()
        via_packages: set[str] = set()
        for via in entry.get("via", []):
            if isinstance(via, dict):
                advisories.update(
                    match.group(0).upper() for match in _ADVISORY_PATTERN.finditer(str(via.get("url", "")))
                )
            elif isinstance(via, str) and via:
                via_packages.add(via.lower())
        findings.append(
            Finding(
                ecosystem=ecosystem,
                package=str(entry.get("name", name)).lower(),
                severity=str(entry.get("severity", "")).lower() or None,
                advisory_ids=tuple(sorted(advisories)),
                surface=surface,
                via_packages=tuple(sorted(via_packages)),
            )
        )
    return tuple(findings)


def split_npm_surfaces(full: tuple[Finding, ...], production: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Production findings win; whatever only the full audit sees is dev-only."""
    production_packages = {(finding.ecosystem, finding.package) for finding in production}
    development = tuple(finding for finding in full if (finding.ecosystem, finding.package) not in production_packages)
    return production + development


def match_ledger(finding: Finding, entries: tuple[LedgerEntry, ...]) -> LedgerEntry | None:
    for entry in entries:
        if entry.ecosystem != finding.ecosystem or entry.package != finding.package:
            continue
        if not entry.advisory_ids or entry.advisory_ids & set(finding.advisory_ids):
            return entry
    return None


def reconcile_findings(
    findings: tuple[Finding, ...],
    entries: tuple[LedgerEntry, ...],
    *,
    block_critical_or_high: bool,
) -> list[dict[str, Any]]:
    """Decide, per finding, whether the ledger may keep it out of the release.

    Severity-unknown Python findings are treated as blocking unless an active
    ledger entry covers them; a critical or high finding on the production
    surface is blocked by ledger policy and cannot be waived at all. A finding
    that only inherits another reported package's advisory is attributed to that
    root instead of demanding a ledger entry of its own.
    """
    present = {(finding.ecosystem, finding.package) for finding in findings}
    reconciled: list[dict[str, Any]] = []
    for finding in findings:
        entry = match_ledger(finding, entries)
        roots = tuple(name for name in finding.via_packages if (finding.ecosystem, name) in present)
        blocking = finding.severity is None or finding.severity in _BLOCKING_SEVERITIES
        if not blocking:
            disposition = "below_release_threshold"
        elif finding.surface == _PRODUCTION_SURFACE and block_critical_or_high:
            disposition = "policy_blocked"
        elif not finding.advisory_ids and roots:
            disposition = "transitive"
            blocking = False
        elif entry is not None and entry.waives():
            disposition = "ledgered"
            blocking = False
        elif entry is not None:
            disposition = "ledger_entry_closed"
        else:
            disposition = "unledgered"
        reconciled.append(
            {
                "advisory_ids": list(finding.advisory_ids),
                "blocking": blocking,
                "disposition": disposition,
                "ecosystem": finding.ecosystem,
                "ledger_id": entry.id if entry is not None else None,
                "package": finding.package,
                "severity": finding.severity,
                "surface": finding.surface,
                "via": list(roots),
            }
        )
    return reconciled


def dependency_gaps(reconciled: list[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "gap": "dependency_finding_blocking",
            "detail": (
                f"{row['ecosystem']} {row['package']} "
                f"severity={row['severity'] or 'unknown'} surface={row['surface']} "
                f"disposition={row['disposition']}"
            ),
        }
        for row in reconciled
        if row["blocking"]
    )


# --------------------------------------------------------------------------
# command execution and logging
# --------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_command(
    command: list[str],
    *,
    env: dict[str, str],
    timeout: float,
    cwd: Path = _REPO_ROOT,
) -> CommandResult:
    """Run one layer command, resolving the executable to an absolute path."""
    executable = command[0] if Path(command[0]).is_absolute() else shutil.which(command[0])
    if executable is None:
        return CommandResult(list(command), None, "", f"executable not found: {command[0]}", "executable_missing")
    resolved = [executable, *command[1:]]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            resolved,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            resolved, None, _decode(exc.stdout), _decode(exc.stderr), "timeout", time.monotonic() - started
        )
    except OSError as exc:
        return CommandResult(resolved, None, "", str(exc), "spawn_error", time.monotonic() - started)
    return CommandResult(
        resolved,
        completed.returncode,
        completed.stdout,
        completed.stderr,
        "completed",
        time.monotonic() - started,
    )


@lru_cache(maxsize=1)
def live_feishu_redactor() -> Callable[[str], str]:
    """Load V-LF's own redactor by path, since scripts/ is not an import package.

    The V-LF stream carries live Feishu identifiers, so its redactor has to run
    over anything V-R0 persists; re-deriving the rules here would let the two
    definitions drift apart.
    """
    spec = importlib.util.spec_from_file_location(
        "pico_release_verify_live_feishu", _REPO_ROOT / "scripts" / "verify_live_feishu.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/verify_live_feishu.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.redact_text


def write_log(path: Path, results: list[CommandResult], *, redact: Callable[[str], str] | None = None) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        f"$ {shlex.join(result.command)}\n"
        f"outcome: {result.outcome}\n"
        f"exit: {result.exit_code}\n"
        f"elapsed_seconds: {result.elapsed_seconds:.3f}\n\n"
        f"[stdout]\n{result.stdout}\n\n"
        f"[stderr]\n{result.stderr}\n"
        for result in results
    ]
    text = "\n".join(sections) if sections else "no command was run\n"
    path.write_text(redact(text) if redact is not None else text, encoding="utf-8")
    return _sha256_file(path)


def load_report(path: Path) -> tuple[dict[str, Any] | None, float | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        produced_at = path.stat().st_mtime
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    return (payload if isinstance(payload, dict) else None), produced_at


def _deciding_exit_code(results: list[CommandResult]) -> int | None:
    for result in results:
        if result.exit_code != 0:
            return result.exit_code
    return 0 if results else None


def build_layer_record(
    spec: LayerSpec,
    *,
    status: str,
    results: list[CommandResult],
    log_path: Path,
    log_sha256: str,
    gaps: tuple[dict[str, str], ...] = (),
    report_path: Path | None = None,
    report_sha256: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "command": [result.command for result in results],
        "evidence_class": spec.evidence_class,
        "exit_code": _deciding_exit_code(results),
        "gaps": [dict(gap) for gap in gaps],
        "gate": spec.gate,
        "layer": spec.name,
        "log": log_path.name,
        "log_sha256": log_sha256,
        "status": resolve_layer_status(status, gaps),
    }
    if report_path is not None:
        record["report_path"] = str(report_path)
        record["report_sha256"] = report_sha256
    if extra:
        record.update(extra)
    return record


def skipped_record(spec: LayerSpec, *, gap: str, detail: str, status: str = SKIPPED) -> dict[str, Any]:
    return {
        "command": [],
        "evidence_class": spec.evidence_class,
        "exit_code": None,
        "gaps": [{"gap": gap, "detail": detail}],
        "gate": spec.gate,
        "layer": spec.name,
        "log": None,
        "log_sha256": None,
        "status": status,
    }


# --------------------------------------------------------------------------
# layer handlers
# --------------------------------------------------------------------------


def _gate_layer(
    context: ReleaseContext,
    spec: LayerSpec,
    command: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
    report_path: Path | None = None,
    extra: dict[str, Any] | None = None,
    redact: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    env = {**context.environ, **(env_overrides or {})}
    started = time.time()
    result = run_command(command, env=env, timeout=spec.timeout)
    log_path = context.logs / f"{spec.name}.log"
    log_sha256 = write_log(log_path, [result], redact=redact)
    status = classify_exit(result.exit_code, result.output, outcome=result.outcome)
    gaps: tuple[dict[str, str], ...] = ()
    report_sha256: str | None = None
    details = dict(extra or {})
    if report_path is not None:
        payload, produced_at = load_report(report_path)
        gaps, binding = bind_report(payload, head=context.head, produced_at=produced_at, layer_started=started)
        details.update(binding)
        if payload is not None and report_path.is_file():
            report_sha256 = _sha256_file(report_path)
    return build_layer_record(
        spec,
        status=status,
        results=[result],
        log_path=log_path,
        log_sha256=log_sha256,
        gaps=gaps,
        report_path=report_path,
        report_sha256=report_sha256,
        extra=details,
    )


def run_v_d0(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    return _gate_layer(context, spec, ["make", "test-retained"])


def run_v_t0(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    return _gate_layer(context, spec, ["make", "lint-tui", "test-tui", "build-tui"])


def run_v_p0(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    distribution_root = Path(tempfile.mkdtemp(prefix="pico-release-vp0-")) / "distribution"
    context.distribution_root = distribution_root
    report_path = distribution_root / "distribution-report.json"
    command = [
        sys.executable,
        str(_REPO_ROOT / "scripts" / "verify_distribution.py"),
        "--output-root",
        str(distribution_root),
        "--entrypoint",
        _DISTRIBUTION_ENTRYPOINT,
        "--extras",
        _DISTRIBUTION_EXTRAS,
    ]
    record = _gate_layer(context, spec, command, report_path=report_path, extra={"output_root": str(distribution_root)})
    payload, _ = load_report(report_path)
    if record["status"] == PASSED and payload is not None and payload.get("status") == PASSED:
        handoff = payload.get("handoff")
        if isinstance(handoff, dict):
            context.handoff = handoff
    return record


def _handoff_value(context: ReleaseContext, *keys: str) -> str | None:
    node: Any = context.handoff
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, str) and node else None


def _handoff_blocked(spec: LayerSpec) -> dict[str, Any]:
    return skipped_record(
        spec,
        gap="distribution_handoff_missing",
        detail="V-P0 did not hand off a verified wheel, so this layer measured nothing",
        status=INCONCLUSIVE,
    )


def run_host_gate(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    wheel = _handoff_value(context, "wheel")
    if wheel is None:
        return _handoff_blocked(spec)
    return _gate_layer(context, spec, ["make", "verify-runtime-hosts"], env_overrides={"PICO_WHEEL": wheel})


def run_v_lp(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    missing = missing_environment(_LIVE_PROVIDER_ENV, context.environ)
    if missing:
        return skipped_record(
            spec,
            gap="live_provider_credentials_missing",
            detail=f"required environment is absent: {list(missing)}",
            status=FAILED,
        )
    wheel = _handoff_value(context, "wheel")
    if wheel is None:
        return _handoff_blocked(spec)
    return _gate_layer(context, spec, ["make", "verify-live-provider"], env_overrides={"PICO_WHEEL": wheel})


def run_v_c0_s0(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    report_path = _REPO_ROOT / ".pico" / "evidence" / "channels" / "channels-report.json"
    return _gate_layer(context, spec, ["make", "verify-channels"], report_path=report_path)


def run_v_lf(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    missing = missing_environment(_LIVE_FEISHU_ENV, context.environ)
    if missing:
        return skipped_record(
            spec,
            gap="feishu_credentials_missing",
            detail=f"required environment is absent: {list(missing)}",
            status=FAILED,
        )
    wheel = _handoff_value(context, "wheel")
    overrides = {"PICO_WHEEL": wheel} if wheel else {}
    report_path = _REPO_ROOT / ".pico" / "evidence" / "feishu" / "feishu-live-report.json"
    return _gate_layer(
        context,
        spec,
        ["make", "verify-live-feishu"],
        env_overrides=overrides,
        report_path=report_path,
        extra={"runtime_source": "wheel" if wheel else "checkout"},
        redact=live_feishu_redactor(),
    )


def run_memory_continuity(
    context: ReleaseContext,
    spec: LayerSpec,
) -> dict[str, Any]:
    del context
    return skipped_record(
        spec,
        gap="myna_release_unavailable",
        detail=(
            "the compatible myna-memory distribution is not available from a "
            "formal artifact source, so V-R0 cannot reproduce the installed "
            "composition from publishable dependencies"
        ),
        status=INCONCLUSIVE,
    )


def run_v_te0(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    report_path = _REPO_ROOT / ".pico" / "evidence" / "turns" / "turn-evidence-report.json"
    return _gate_layer(context, spec, ["make", "verify-turn-evidence"], report_path=report_path)


def run_v_e0(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    return _gate_layer(context, spec, ["make", "verify-evolver"])


def run_assets(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    """Pin the range the asset gate inspects and refuse to pass on an empty one.

    ``make check-large-files`` exits 0 when its range adds or modifies nothing,
    which at a release candidate commit is the common case rather than a pass.
    """
    commit_range = context.environ.get(_ASSET_RANGE_ENV) or _ASSET_DEFAULT_RANGE
    covered = changed_paths(commit_range)
    if not covered:
        return skipped_record(
            spec,
            gap="asset_scope_empty",
            detail=f"{commit_range} resolves to no added or modified file, so the asset gate examined nothing",
            status=INCONCLUSIVE,
        )
    return _gate_layer(
        context,
        spec,
        ["make", "check-large-files"],
        env_overrides={_ASSET_RANGE_ENV: commit_range},
        extra={"changed_paths": len(covered), "commit_range": commit_range},
    )


def run_deps_audit(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    commands = {
        "pip_audit": [
            sys.executable,
            "-m",
            "pip_audit",
            "-f",
            "json",
            "--desc",
            "off",
            "--aliases",
            "on",
            "--progress-spinner",
            "off",
        ],
        "npm_audit": ["npm", "audit", "--prefix", "ui-tui", "--json"],
        "npm_audit_production": ["npm", "audit", "--prefix", "ui-tui", "--omit=dev", "--json"],
    }
    results: dict[str, CommandResult] = {
        name: run_command(command, env=context.environ, timeout=spec.timeout) for name, command in commands.items()
    }
    log_path = context.logs / f"{spec.name}.log"
    log_sha256 = write_log(log_path, list(results.values()))

    payloads: dict[str, dict[str, Any] | None] = {}
    unreadable: list[str] = []
    for name, result in results.items():
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict) or _AUDIT_RESULT_KEY[name] not in payload:
            payload = None
            unreadable.append(name)
        payloads[name] = payload

    gaps: list[dict[str, str]] = [
        {
            "gap": "dependency_audit_unreadable",
            "detail": (
                f"{name} emitted no {_AUDIT_RESULT_KEY[name]} result "
                f"(outcome {results[name].outcome}, exit {results[name].exit_code})"
            ),
        }
        for name in unreadable
    ]
    status = INFRASTRUCTURE_FAILURE if unreadable else PASSED
    findings: tuple[Finding, ...] = ()
    reconciled: list[dict[str, Any]] = []
    entries: tuple[LedgerEntry, ...] = ()
    block_critical_or_high = True
    if not unreadable:
        try:
            ledger_payload = tomllib.loads((_REPO_ROOT / LEDGER_PATH).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            ledger_payload = {}
            gaps.append({"gap": "exception_ledger_unreadable", "detail": f"{LEDGER_PATH} could not be parsed"})
            status = INFRASTRUCTURE_FAILURE
        entries, block_critical_or_high = load_ledger(ledger_payload)
        npm_findings = split_npm_surfaces(
            parse_npm_audit(payloads["npm_audit"] or {}, ecosystem=_NPM_UI_TUI_ECOSYSTEM, surface=_DEVELOPMENT_SURFACE),
            parse_npm_audit(
                payloads["npm_audit_production"] or {}, ecosystem=_NPM_UI_TUI_ECOSYSTEM, surface=_PRODUCTION_SURFACE
            ),
        )
        findings = parse_pip_audit(payloads["pip_audit"] or {}) + npm_findings
        reconciled = reconcile_findings(findings, entries, block_critical_or_high=block_critical_or_high)
        blocking = dependency_gaps(reconciled)
        gaps.extend(blocking)
        if blocking and status == PASSED:
            status = FAILED

    report_path = context.output_root / DEPENDENCY_REPORT_FILENAME
    report_path.write_text(
        json.dumps(
            {
                "commit": context.head,
                "findings": reconciled,
                "ledger": str(LEDGER_PATH),
                "policy": {"release_blocks_critical_or_high": block_critical_or_high},
                "sources": {name: result.command for name, result in results.items()},
                "status": status,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return build_layer_record(
        spec,
        status=status,
        results=list(results.values()),
        log_path=log_path,
        log_sha256=log_sha256,
        gaps=tuple(gaps),
        report_path=report_path,
        report_sha256=_sha256_file(report_path),
        extra={"blocking_findings": sum(1 for row in reconciled if row["blocking"]), "findings": len(findings)},
    )


def _interrupt_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        return
    os.killpg(process.pid, signal.SIGINT)


def _kill_process(process: subprocess.Popen) -> None:
    if os.name == "nt":
        process.kill()
        return
    os.killpg(process.pid, signal.SIGKILL)


def run_until_interrupt(
    command: list[str],
    *,
    env: dict[str, str],
    scratch: Path,
    settle_seconds: float,
    shutdown_seconds: float,
    cwd: Path = _REPO_ROOT,
) -> CommandResult:
    """Start a command, interrupt it once it is running, and wait for its exit.

    ``outcome`` is ``interrupted`` only when the process was still alive at the
    interrupt deadline; an early exit leaves the resume claim unproven.
    """
    executable = command[0] if Path(command[0]).is_absolute() else shutil.which(command[0])
    if executable is None:
        return CommandResult(list(command), None, "", f"executable not found: {command[0]}", "executable_missing")
    resolved = [executable, *command[1:]]
    scratch.mkdir(parents=True, exist_ok=True)
    stdout_path = scratch / "interrupted-stdout.log"
    stderr_path = scratch / "interrupted-stderr.log"
    options: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    )
    started = time.monotonic()
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        try:
            process = subprocess.Popen(resolved, cwd=cwd, env=env, stdout=out, stderr=err, text=True, **options)
        except OSError as exc:
            return CommandResult(resolved, None, "", str(exc), "spawn_error", time.monotonic() - started)
        deadline = started + settle_seconds
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.5)
        interrupted = process.poll() is None
        if interrupted:
            try:
                _interrupt_process(process)
            except (OSError, ProcessLookupError):
                interrupted = False
        outcome = "interrupted" if interrupted else "completed"
        try:
            process.wait(timeout=shutdown_seconds)
        except subprocess.TimeoutExpired:
            try:
                _kill_process(process)
            except (OSError, ProcessLookupError):
                pass
            process.wait(timeout=60)
            outcome = "timeout"
    return CommandResult(
        resolved,
        process.returncode,
        stdout_path.read_text(encoding="utf-8", errors="replace"),
        stderr_path.read_text(encoding="utf-8", errors="replace"),
        outcome,
        time.monotonic() - started,
    )


def run_evolution(context: ReleaseContext, spec: LayerSpec) -> dict[str, Any]:
    missing = missing_small_real_inputs(_REPO_ROOT)
    if missing:
        return skipped_record(
            spec,
            gap="small_real_files_missing",
            detail=f"the small real Evolution Run inputs are absent: {list(missing)}",
            status=INCONCLUSIVE,
        )
    entrypoint = _handoff_value(context, "base_environment", "entrypoint")
    if entrypoint is None:
        return _handoff_blocked(spec)

    scratch = context.output_root / "evolution"
    scratch.mkdir(parents=True, exist_ok=True)
    config = str(_REPO_ROOT / _SMALL_REAL_CONFIG)
    results: list[CommandResult] = []
    gaps: list[dict[str, str]] = []
    status = PASSED

    setup = run_command(
        [sys.executable, str(_REPO_ROOT / _SMALL_REAL_SETUP)],
        env=context.environ,
        timeout=spec.timeout,
    )
    results.append(setup)
    status = classify_exit(setup.exit_code, setup.output, outcome=setup.outcome)

    if status == PASSED:
        check = run_command(
            [entrypoint, "evolve", "check", "--config", config], env=context.environ, timeout=spec.timeout
        )
        results.append(check)
        status = classify_exit(check.exit_code, check.output, outcome=check.outcome)

    if status == PASSED:
        interrupted = run_until_interrupt(
            [entrypoint, "evolve", "run", "--config", config],
            env=context.environ,
            scratch=scratch,
            settle_seconds=_EVOLUTION_INTERRUPT_SECONDS,
            shutdown_seconds=_EVOLUTION_SHUTDOWN_SECONDS,
        )
        results.append(interrupted)
        if interrupted.outcome == "timeout":
            status = INFRASTRUCTURE_FAILURE
        elif interrupted.outcome != "interrupted":
            status = INCONCLUSIVE
            gaps.append(
                {
                    "gap": "evolution_interrupt_not_observed",
                    "detail": "the run exited before the interrupt, so resume was never exercised",
                }
            )

    if status == PASSED:
        for step in (
            ["evolve", "run", "--config", config],
            ["evolve", "status", "--config", config],
            ["evolve", "finalize", "--config", config, "--yes"],
        ):
            result = run_command([entrypoint, *step], env=context.environ, timeout=spec.timeout)
            results.append(result)
            status = classify_exit(result.exit_code, result.output, outcome=result.outcome)
            if status != PASSED:
                break

    log_path = context.logs / f"{spec.name}.log"
    log_sha256 = write_log(log_path, results)
    return build_layer_record(
        spec,
        status=status,
        results=results,
        log_path=log_path,
        log_sha256=log_sha256,
        gaps=tuple(gaps),
        extra={"config": config, "entrypoint": entrypoint},
    )


HANDLERS = {
    "v_d0": run_v_d0,
    "v_t0": run_v_t0,
    "v_p0": run_v_p0,
    "host_gate": run_host_gate,
    "v_lp": run_v_lp,
    "v_c0_s0": run_v_c0_s0,
    "v_lf": run_v_lf,
    "memory_continuity": run_memory_continuity,
    "v_te0": run_v_te0,
    "v_e0": run_v_e0,
    "deps_audit": run_deps_audit,
    "assets": run_assets,
    "evolution": run_evolution,
}


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def _git(arguments: list[str]) -> str:
    executable = shutil.which("git")
    if executable is None:
        return ""
    completed = subprocess.run([executable, *arguments], cwd=_REPO_ROOT, capture_output=True, text=True, check=False)
    return completed.stdout if completed.returncode == 0 else ""


def head_commit() -> str:
    return _git(["rev-parse", "HEAD"]).strip()


def worktree_is_clean() -> bool:
    return not _git(["status", "--porcelain=v1", "--untracked-files=normal"]).strip()


def changed_paths(commit_range: str) -> tuple[str, ...]:
    """The files scripts/check_large_files.py would inspect for this range."""
    output = _git(["diff", "--name-only", "--diff-filter=AM", commit_range])
    return tuple(line for line in output.splitlines() if line)


def run_layers(context: ReleaseContext, selection: tuple[str, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for spec in LAYERS:
        if spec.name not in selection:
            records.append(
                skipped_record(
                    spec,
                    gap="layer_not_run",
                    detail="the layer was not selected, so this run cannot describe a release",
                )
            )
            continue
        record = HANDLERS[spec.name](context, spec)
        print(f"{GATE} {spec.name} {record['status']}")
        records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the V-R0 release candidate gate.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--layers",
        default=None,
        help=f"comma-separated development subset of {','.join(LAYER_NAMES)}; only the full set can pass",
    )
    args = parser.parse_args(argv)

    try:
        selection = select_layers(args.layers)
    except ValueError as exc:
        print(f"{GATE} invalid selection: {exc}", file=sys.stderr)
        return 2

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    context = ReleaseContext(
        output_root=output_root,
        head=head_commit(),
        worktree_clean=worktree_is_clean(),
        environ=dict(os.environ),
    )
    records = run_layers(context, selection)
    report = build_report(
        records,
        head=context.head,
        worktree_clean=context.worktree_clean,
        selection=selection,
        handoff=context.handoff,
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    report_path = output_root / REPORT_FILENAME
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{GATE} {report['status']}: {report_path}")
    return 0 if report["status"] == PASSED else 1


if __name__ == "__main__":
    raise SystemExit(main())
