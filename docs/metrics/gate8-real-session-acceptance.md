# Gate8 Real Session Acceptance

Gate8 is Pico's deterministic evidence harness. It does not add runtime
features. It proves the current runtime can produce inspectable session
artifacts for the features that matter in an interview or review.

Run it from the repo root:

```bash
uv run python scripts/run_real_session_acceptance.py \
  --output-dir artifacts/gate8-real-session-acceptance
```

The command creates:

- `gate8-real-session-acceptance.json`
- `gate8-real-session-acceptance.md`
- `workspaces/<scenario>/.pico/sessions/*.events.jsonl`
- `workspaces/<scenario>/.pico/runs/<run_id>/task_state.json`
- `workspaces/<scenario>/.pico/runs/<run_id>/trace.jsonl`
- `workspaces/<scenario>/.pico/runs/<run_id>/report.json`

The deterministic required scenarios are:

- `bugfix_pytest`: real Python fixture, failing pytest, file patch, test
  rerun, and changed-path evidence.
- `plan_todo_explore`: PlanMode, todo ledger, Explore subagent, active plan
  artifact, session events, and report workers.
- `skill_inline`: project skill invocation, allowed tool profile, skill events,
  and run artifacts.
- `worker_write_scope`: worker spawn, `send_message` continuation, scoped file
  writes, worker notifications, and report workers.
- `resume_continuation`: session reload, persisted todo state, continued file
  write, and resume status in the final report.
- `security_rejection`: workspace path escape rejection, worker write-scope
  rejection, secret redaction, rejected metadata, and final report.
- `context_pressure`: long workspace context, manual compaction, constrained
  prompt budget, target patch, and report-level context usage.
- `provider_error_recovery`: structured provider error classification, failed
  run status, retry metadata, session event, trace, and report evidence.

The optional scenario is:

- `live_provider_smoke`: one low-risk live provider request. It is skipped
  unless `PICO_ACCEPTANCE_LIVE=1` or `--live-provider` is set and a provider
  API key is available.

The acceptance source is the generated evidence bundle, not a model's final
claim. A passing required scenario means it ended with
`stop_reason=final_answer_returned`, wrote a report and trace, and emitted a
session event timeline.
