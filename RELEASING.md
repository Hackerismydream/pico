# Releasing Pico

How a new Pico version is cut and published.

## Versioning

- Semantic versioning `MAJOR.MINOR.PATCH`. The source of truth is `version` in
  `pyproject.toml`.
- Tags: `vX.Y.Z` for a stable release, `vX.Y.Z-rcN` for a pre-release. The tag
  must match the `pyproject.toml` version -- CI enforces this (`release.yml`).
- For a pre-release, keep `pyproject.toml` at the base version (e.g. `0.1.3`
  while tagging `v0.1.3-rc1`); CI compares only the base. Do NOT set the
  version to `0.1.3-rc1` -- that is not a version hatch will build.

## Release title

`Pico X.Y.Z (YYYY-MM-DD)` -- for example `Pico 0.2.0 (2026-07-24)`. The CI
draft fills this in automatically (date is the build date; adjust when
publishing if needed).

## Release notes

Notes are hand-written and curated. The CI draft prefills the boilerplate
(Install, Release Status, Notes); a human writes the one-line summary and the
Highlights before publishing. Structure:

```
<one-line summary>

## Highlights
- <user-facing change>

## Install
  uv tool install ./pico_harness-X.Y.Z-py3-none-any.whl
  then: pico onboard

## Release Status
- Version: `X.Y.Z`
- Tag: `vX.Y.Z`
- Stability: <public preview patch | public preview minor | ...>   # fill by hand per release type
- Assets: wheel and source distribution attached to this release

## Notes
- pre-1.0 evolution caveat
- PyPI not enabled; install via the GitHub Release wheel
```

`Stability` is not boilerplate -- set it by release type (patch / minor / rc).

## Pre-tag gates

Run these before step 1 of Flow. The aggregate entry is V-R0:
`make verify-release` runs every layer below plus the dependency audit, the
asset gate, and the small real Evolution Run, and writes one commit-bound
report. Commands, required environment variables, and evidence outputs are
documented in [docs/dev.md](docs/dev.md).

| Gate | Command | Covers |
| --- | --- | --- |
| V-R0 | `make verify-release` | Every layer below, assembled into one commit-bound release report |
| V-D0 | `make test-retained` | The retained deterministic Runtime suite |
| V-C0, V-S0 | `make verify-channels` | Channel contract bundle and Channel security and isolation bundle |
| Memory continuity | blocked until `myna-memory` is formally available | Reproduce the installed Pico plus Myna composition from publishable artifacts before V-R0 can pass |
| V-TE0 | `make verify-turn-evidence` | Tracing, usage, and delivery correlation for one Turn |
| V-E0 | `make verify-evolver` | The opt-in Evolver Beta surface |
| V-P0 | `scripts/verify_distribution.py` | Wheel and source distribution build, manifest, and install probes |
| - | `make verify-runtime-hosts` | CLI, TUI, and Gateway from the V-P0 wheel |

V-LP (`make verify-live-provider`) and V-LF (`make verify-live-feishu`) are
operator-run live Gates: they require real credentials, and V-LF also requires
a human to provide the inbound stimulus. A skipped or inconclusive result never
satisfies them. If a release ships without a passed live Gate, say so in the
release notes rather than leaving live coverage implied. The current
capability-to-Gate mapping is
[docs/feature-evidence.md](docs/feature-evidence.md).

The historical EverOS and CodeCairn commands were removed with those
integrations. V-R0 records the replacement `memory_continuity` layer as
inconclusive until the compatible Myna distribution can be resolved from a
formal artifact source and the installed composition is reproducible.

## Flow

1. Bump `version` in `pyproject.toml`; open a PR; merge to `main`.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. CI (`release.yml`) builds the wheel + sdist and creates a **draft** GitHub
   Release with both attached, titled and prefilled from the template.
4. Fill the summary + Highlights in the draft, then click **Publish**.
   Publishing makes it `/releases/latest`.

## Pre-releases

- `vX.Y.Z-rcN` tags build a draft marked **pre-release**. A pre-release is never
  `/releases/latest`. Use an rc tag to verify the release pipeline before
  cutting the stable tag; delete the rc release and tag afterward.

## Notes

- `main` is squash-merge + PR-only. The release itself is not automated past the
  draft: publishing is a deliberate human step.
- PyPI publishing is not wired up; the supported install path is the wheel
  attached to the GitHub Release.
