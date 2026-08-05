# Pico checkout-only scripts

These utilities run from a source checkout and are not part of the
`pico-harness` wheel. Use `uv run python scripts/<name>.py`.

## Repository policy and CI checks

| Script | Purpose |
| --- | --- |
| `check_commit_file.py` | validate one commit-message file |
| `check_commit_messages.py` | validate a commit range |
| `check_pr_body.py` | enforce PR body ASCII and repository policy |
| `check_pr_title.py` | enforce Conventional Commit PR title |
| `check_large_files.py` | reject report assets and files over the repository limit |
| `commit_lint.py` | shared Conventional Commit parser/validation |

Prefer the Make targets:

```bash
make check-commits
make check-large-files
```

## Release and continuity verifiers

| Script | Purpose | Canonical caller |
| --- | --- | --- |
| `verify_distribution.py` | isolated TUI/wheel/sdist build, exact wheel manifest, isolated retained-extra installs, installed probes, sdist-to-wheel equivalence | V-P0 in `docs/dev.md` and release workflow |
| `verify_channels.py` | deterministic V-C0 Channel contract and V-S0 security/isolation report | `make verify-channels` |
| `verify_live_feishu.py` | operator-in-the-loop V-LF tracer bullet with redacted evidence | `make verify-live-feishu` |
| `verify_turn_evidence.py` | deterministic V-TE0 Turn trace, usage, delivery, and terminal-state correlation | `make verify-turn-evidence` |
| `verify_release.py` | V-R0 orchestration over every required layer at one clean commit | `make verify-release` |
| `setup_small_real_subject.py` | materialize the disposable subject repository for the small-real Evolution Run | V-R0 evolution layer and `benchmarks/evolver/README.md` |

These scripts emit machine-readable reports under the caller-supplied or
documented output root. Only a report with `status = passed` may provide its
handoff paths to a downstream Gate.

## SkillForge evaluation

| Script | Purpose |
| --- | --- |
| `skill_forge_retrieval_eval.py` | self-contained offline retrieval evaluation over `benchmarks/skill_evals/queries.jsonl` |
| `skill_forge_full_e2e.py` | broader configured SkillForge pipeline probe |

The offline retrieval evaluation does not prove CodeCairn persistence or
Provider behavior.

## Sandbox administration

`boxlite_cli.py` manages BoxLite directly:

- image list/pull/remove;
- VM create/list/start/stop/remove/shell;
- explicit BoxLite home selection.

It differs from `pico sandbox`, which talks to the debug server of one running
Pico process and restricts exec/shell to VMs owned by that process.

See [`docs/sandbox/boxlite_cli.md`](../docs/sandbox/boxlite_cli.md).

Inspect Pico's BoxLite home:

```bash
PICO_BOXLITE_HOME="$(
  uv run python -c \
    'from pico.config.paths import get_sandbox_dir; print(get_sandbox_dir("boxlite"))'
)"
uv run python scripts/boxlite_cli.py \
  --home-dir "$PICO_BOXLITE_HOME" vm ls
```

## Evidence rules

- never commit keys, tokens, account ids, sensitive prompts, or live recalled
  content;
- distinguish deterministic, live, skipped, Provider, and infrastructure
  results;
- bind release evidence to a commit;
- keep large logs outside Git;
- do not describe a diagnostic script's successful startup as end-to-end
  product success.
