from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from benchmarks.picobench.codecairn_continuity import (
    PairIntegrityError,
    audit_pair_inputs,
)


def test_pair_audit_verifies_current_and_historical_artifacts(
    tmp_path: Path,
) -> None:
    current_pico = _wheel(tmp_path / "pico-current.whl", "pico-harness", "0.1.7")
    implementation_pico = _wheel(
        tmp_path / "pico-implementation.whl",
        "pico-harness",
        "0.1.7",
    )
    compatibility_pico = _wheel(
        tmp_path / "pico-compatibility.whl",
        "pico-harness",
        "0.1.7",
    )
    codecairn = _wheel(
        tmp_path / "codecairn.whl",
        "codecairn",
        "0.1.0",
        entry_points="[pico.plugins]\ncodecairn = codecairn.integrations.pico\n",
    )
    codecairn_commit = "c" * 40
    implementation_commit = "a" * 40
    compatibility_commit = "b" * 40
    pico_handoff = _write_json(
        tmp_path / "pico-handoff.json",
        {
            "schema_version": 1,
            "kind": "pico.codecairn.implementation.handoff",
            "pico": {
                "commit": implementation_commit,
                "distribution": {
                    "name": "pico-harness",
                    "version": "0.1.7",
                    "wheel_sha256": _sha256(implementation_pico),
                },
            },
            "codecairn": {
                "commit": codecairn_commit,
                "install_spec": ("codecairn @ git+https://example.invalid/CodeCairn.git@" + codecairn_commit),
                "distribution_name": "codecairn",
                "distribution_version": "0.1.0",
                "handoff_sha256": "",
                "wheel_sha256": _sha256(codecairn),
            },
            "plugin_contract": _contract(),
        },
    )
    codecairn_handoff = _write_json(
        tmp_path / "codecairn-handoff.json",
        {
            "schema_version": 1,
            "kind": "codecairn.pico.adapter.handoff",
            "codecairn": {
                "commit": codecairn_commit,
                "install_spec": ("codecairn @ git+https://example.invalid/CodeCairn.git@" + codecairn_commit),
                "distribution": {"name": "codecairn", "version": "0.1.0"},
                "wheel": {
                    "sha256": _sha256(codecairn),
                },
            },
            "pico": {
                "commit": compatibility_commit,
                "wheel": {
                    "sha256": _sha256(compatibility_pico),
                },
            },
            "plugin_inventory": {
                "entry_points": [
                    {
                        "group": "pico.plugins",
                        "name": "codecairn",
                        "value": "codecairn.integrations.pico",
                    }
                ],
                "plugins": [
                    {
                        "id": "codecairn-memory",
                        "memory_backends": ["codecairn"],
                        "tools": [],
                    }
                ],
            },
        },
    )
    pico_handoff_data = json.loads(pico_handoff.read_text())
    pico_handoff_data["codecairn"]["handoff_sha256"] = _sha256(codecairn_handoff)
    pico_handoff.write_text(
        json.dumps(pico_handoff_data, sort_keys=True),
        encoding="utf-8",
    )
    distribution_report = _distribution_report(
        tmp_path / "distribution-report.json",
        commit="d" * 40,
        wheel=current_pico,
    )

    result = audit_pair_inputs(
        pico_wheel=current_pico,
        codecairn_wheel=codecairn,
        pico_handoff=pico_handoff,
        codecairn_handoff=codecairn_handoff,
        pico_implementation_wheel=implementation_pico,
        pico_compatibility_wheel=compatibility_pico,
        pico_distribution_report=distribution_report,
        pico_commit="d" * 40,
    )

    assert result.pico_commit == "d" * 40
    assert result.codecairn_commit == codecairn_commit
    assert result.current_pico_wheel_sha256 == _sha256(current_pico)
    assert result.codecairn_wheel_sha256 == _sha256(codecairn)
    assert result.plugin_contract == _contract()
    assert result.historical_pico_wheel_sha256 == {
        "codecairn_compatibility": _sha256(compatibility_pico),
        "pico_implementation": _sha256(implementation_pico),
    }


def test_pair_audit_rejects_unverified_nested_handoff_digest(
    tmp_path: Path,
) -> None:
    pico = _wheel(tmp_path / "pico.whl", "pico-harness", "0.1.7")
    codecairn = _wheel(
        tmp_path / "codecairn.whl",
        "codecairn",
        "0.1.0",
        entry_points="[pico.plugins]\ncodecairn = codecairn.integrations.pico\n",
    )
    codecairn_handoff = _write_json(
        tmp_path / "codecairn-handoff.json",
        {
            "schema_version": 1,
            "kind": "codecairn.pico.adapter.handoff",
            "codecairn": {
                "commit": "c" * 40,
                "install_spec": "codecairn @ git+https://example.invalid/repo@" + "c" * 40,
                "distribution": {"name": "codecairn", "version": "0.1.0"},
                "wheel": {"sha256": _sha256(codecairn)},
            },
            "pico": {
                "commit": "b" * 40,
                "wheel": {"sha256": "f" * 64},
            },
            "plugin_inventory": {
                "entry_points": [
                    {
                        "group": "pico.plugins",
                        "name": "codecairn",
                        "value": "codecairn.integrations.pico",
                    }
                ],
                "plugins": [
                    {
                        "id": "codecairn-memory",
                        "memory_backends": ["codecairn"],
                        "tools": [],
                    }
                ],
            },
        },
    )
    pico_handoff = _write_json(
        tmp_path / "pico-handoff.json",
        {
            "schema_version": 1,
            "kind": "pico.codecairn.implementation.handoff",
            "pico": {
                "commit": "a" * 40,
                "distribution": {
                    "name": "pico-harness",
                    "version": "0.1.7",
                    "wheel_sha256": _sha256(pico),
                },
            },
            "codecairn": {
                "commit": "c" * 40,
                "install_spec": "codecairn @ git+https://example.invalid/repo@" + "c" * 40,
                "distribution_name": "codecairn",
                "distribution_version": "0.1.0",
                "handoff_sha256": _sha256(codecairn_handoff),
                "wheel_sha256": _sha256(codecairn),
            },
            "plugin_contract": _contract(),
        },
    )

    with pytest.raises(
        PairIntegrityError,
        match="CodeCairn compatibility Pico wheel digest",
    ):
        distribution_report = _distribution_report(
            tmp_path / "distribution-report.json",
            commit="d" * 40,
            wheel=pico,
        )
        audit_pair_inputs(
            pico_wheel=pico,
            codecairn_wheel=codecairn,
            pico_handoff=pico_handoff,
            codecairn_handoff=codecairn_handoff,
            pico_implementation_wheel=pico,
            pico_compatibility_wheel=pico,
            pico_distribution_report=distribution_report,
            pico_commit="d" * 40,
        )


def test_pair_audit_rejects_stale_current_pico_wheel(
    tmp_path: Path,
) -> None:
    wheel = _wheel(
        tmp_path / "pico-current.whl",
        "pico-harness",
        "0.1.7",
    )
    report = _distribution_report(
        tmp_path / "distribution-report.json",
        commit="a" * 40,
        wheel=wheel,
    )

    with pytest.raises(
        PairIntegrityError,
        match="not bound to the clean source commit",
    ):
        from benchmarks.picobench.codecairn_continuity import (
            _verify_pico_distribution_report,
        )

        _verify_pico_distribution_report(
            report,
            pico_commit="b" * 40,
            pico_wheel_sha256=_sha256(wheel),
        )


def _contract() -> dict[str, object]:
    return {
        "backend_factory": "codecairn.integrations.pico.backend:make_backend",
        "entry_point": {
            "group": "pico.plugins",
            "name": "codecairn",
            "value": "codecairn.integrations.pico",
        },
        "memory_backend": "codecairn",
        "plugin_id": "codecairn-memory",
        "resource_package": "codecairn.integrations.pico",
        "source_schema": "codecairn.pico.source.v1",
        "turn_boundary": "pico_turn_end",
    }


def _wheel(
    path: Path,
    name: str,
    version: str,
    *,
    entry_points: str | None = None,
) -> Path:
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.3\nName: {name}\nVersion: {version}\n",
        )
        if entry_points is not None:
            archive.writestr(f"{dist_info}/entry_points.txt", entry_points)
    return path


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _distribution_report(
    path: Path,
    *,
    commit: str,
    wheel: Path,
) -> Path:
    return _write_json(
        path,
        {
            "artifacts": {
                "wheel": {
                    "sha256": _sha256(wheel),
                }
            },
            "schema_version": 3,
            "source": {
                "clean": True,
                "commit": commit,
                "source_manifest_sha256": "e" * 64,
                "unchanged_during_verification": True,
            },
            "source_sha": commit,
            "status": "passed",
        },
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
