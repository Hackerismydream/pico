# PicoBench Live / Dogfood Protocol

## Purpose

Live and dogfood tasks measure whether Pico can handle recent, realistic local
coding work without training-set leakage. They are separate from the public
synthetic core suite.

## Admission Criteria

A task can enter the live queue only when all of these are true:

- The prompt is sanitized and keeps the original user intent.
- The base repo or fixture can be reconstructed from a commit or digest.
- Public setup commands are deterministic.
- Hidden tests are stored outside the public repository.
- The task passes three stability checks with the same expected verifier result.
- The task has quality metadata: clarity, coverage, effort, risk, and source.

## Storage

Public skeletons live under `benchmarks/picobench-live/`. Private hidden tests,
private fixtures, and raw prompts stay outside the public repo.

## Running

Live runs use the same public runner:

```bash
uv run python scripts/run_picobench.py \
  --suite live \
  --benchmark /path/to/private/live-batch.yaml \
  --provider deepseek \
  --approval auto \
  --sandbox best_effort \
  --output-dir /tmp/picobench-live-$(date +%Y%m%d)
```

## Reporting

Do not mix live pass rates with public core pass rates. Report live as a
separate diagnostic track with task count, stability status, hidden-test status,
and failure taxonomy.
