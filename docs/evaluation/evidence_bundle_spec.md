# PicoBench Evidence Bundle Spec

Each live run output directory should contain a complete, redacted evidence
bundle that allows a reviewer to reproduce the score and inspect failures.

## Required Files

```text
summary.json
summary_compact.json
summary.md
task_results.jsonl
logs/
workspaces/
evidence/
failures/
provider_config_redacted.json
run_manifest.json
```

Manual local evidence bundles should keep `workspaces/` for debugging. Public
or GitHub Actions artifacts may omit `workspaces/` because benchmark workspaces
can contain injected hidden tests after scoring.

## `run_manifest.json`

Required fields:

```json
{
  "schema_version": 1,
  "created_at": "...",
  "repo_commit": "...",
  "branch": "...",
  "suite": "...",
  "benchmark": "...",
  "provider": "...",
  "model": "...",
  "approval": "auto",
  "sandbox": "best_effort",
  "task_count": 0,
  "summary_path": "summary.json",
  "evidence_paths": [],
  "notes": ""
}
```

## `provider_config_redacted.json`

Allowed fields:

```json
{
  "provider": "deepseek",
  "protocol": "anthropic",
  "model": "...",
  "base_url_host": "api.deepseek.com",
  "has_api_key": true
}
```

Raw keys, bearer tokens, authorization headers, and full secret-bearing URLs are
not allowed.

## Retention Rules

- Provider/model/base URL host can be saved.
- Token, cost, and duration metrics can be saved.
- Failed task workspaces can be retained for debugging.
- Before publishing or sharing artifacts, inspect workspaces and logs for
  secrets.
- Hidden tests are injected during scoring but must not be published as source
  or included in public artifacts.
- Raw user logs must not be committed into the public repo.

## Review Use

The evidence bundle should let a reviewer answer:

- Which commit and branch were tested?
- Which provider/model/config was used?
- Which tasks ran?
- Which tasks strictly passed or failed?
- Which verifier failed first?
- Is the failure reproducible from the saved workspace and logs?
