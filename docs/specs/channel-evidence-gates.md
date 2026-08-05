# Channel evidence gates: V-C0, V-S0, and V-LF

> Status: current
> Owners: Issue #21 (V-C0, V-LF), Issue #22 (V-C0 extension, V-S0)

This spec defines the three Channel verification Gates referenced by the
product contract: V-C0, the deterministic Channel contract Gate; V-S0, the
deterministic Channel security and isolation Gate; and V-LF, the required real
Feishu tracer bullet. It follows the evidence conventions used by
`scripts/verify_distribution.py` (V-P0): a small driver script, one
machine-readable report, hashed logs, and a shared result vocabulary. The
historical EverOS V-O0 script has been removed; its CodeCairn replacement is an
explicitly blocked `memory_continuity` layer pending separate authority.

## Evidence vocabulary

All Gates reuse the repository result vocabulary defined in
`tests/README.md`:

- `passed` - the named checks ran and every one succeeded;
- `failed` - a check asserted and failed;
- `skipped` - a required input (test, credential) was absent;
- `inconclusive` - the run finished without a usable verdict;
- `provider_failure` - the LLM Provider failed, not the product;
- `infrastructure_failure` - the environment failed (timeout, spawn error).

A skipped or inconclusive result never satisfies a required Gate. Deterministic
and live evidence are recorded separately and never substitute for each other.

## V-C0 and V-S0: deterministic Channel Gates

Two deterministic Gates run from one driver. Both run offline, spend no model
calls, and touch no chat platform.

| Gate | Name | Claim |
| --- | --- | --- |
| V-C0 | Channel contract bundle | Every retained adapter satisfies the inbound, outbound, allowlist, media, retry, and error contracts |
| V-S0 | Channel security and isolation bundle | Channel SDKs stay lazy, allowlists deny by default, and one broken adapter cannot take down the rest |

### V-C0 scope

V-C0 proves the retained Channel layer deterministically: the Channel
Interface contract, adapter registration and lazy SDK discovery, allowlist
enforcement, inbound normalization and dedup, outbound Text and MediaOut
rendering, retryable-versus-terminal error classification, DeliveryHub retry
and isolation, Gateway Spine wiring, and Cron delivery resolution.

V-C0 is a named, rerunnable bundle of existing and future deterministic tests.
It does not start a Gateway, open a websocket, or touch a real Channel
account.

### Runner

`scripts/verify_channels.py` runs each bundle as a separate pytest subprocess
and writes:

```
.pico/evidence/channels/
  channels-report.json      # schema pico.channels.evidence.v2
  contract.log              # full V-C0 pytest output, sha256 in the report
  security.log              # full V-S0 pytest output, sha256 in the report
```

Report fields:

| Field | Meaning |
| --- | --- |
| `schema` | `pico.channels.evidence.v2` |
| `gate` | `V-C0` |
| `security_gate` | `V-S0` |
| `checks.contract` | V-C0 result: command, counts, exit code, selection, log, log hash |
| `checks.security` | V-S0 result: same shape as `checks.contract` |
| `status` | `passed` only when both bundles passed |

The v1 schema carried a single `checks.deterministic` entry; v2 renames it to
`checks.contract` and adds `checks.security`, a breaking shape change under
the schema versioning rule below.

Rerun command:

```bash
make verify-channels
```

The command prints one line per Gate (`V-C0 <status>` and `V-S0 <status>`) and
exits 0 only when both are `passed`. Both bundles are deterministic, so a skip,
an expected failure, or an unexpected pass is a Gate failure, never a pass
(`--strict-markers`, no live markers selected): no result the bundles produce
may be presented as live evidence.

### V-C0 test inventory

The bundle is the Channel-layer deterministic surface; the file list lives in
one place, `scripts/verify_channels.py`.

- `tests/test_auth_allowlist.py`
- `tests/test_channels_base.py`
- `tests/test_channels_contract.py`
- `tests/test_channels_errors.py`
- `tests/test_channels_feishu.py`
- `tests/test_channels_intake.py`
- `tests/test_channels_manager.py`
- `tests/test_channels_media.py`
- `tests/test_channels_outlet.py`
- `tests/test_channels_qq.py`
- `tests/test_channels_registry.py`
- `tests/test_channels_required_marker.py`
- `tests/test_channels_wecom.py`
- `tests/test_cli_channel_commands.py`
- `tests/test_cli_gateway_spine.py`
- `tests/test_config_update_channels.py`
- `tests/test_cron_delivery.py`
- `tests/test_spine_delivery.py`
- `tests/test_verify_channels.py`
- `tests/test_verify_live_feishu.py`

### V-S0 definition

V-S0 is the deterministic Channel security and isolation bundle. It is a named
selection, not a whole-directory sweep, so a renamed or deleted test fails the
Gate instead of quietly shrinking it. Three claims:

1. **SDK laziness.** Subprocess probes assert that importing a channel's
   `spec.py`, or running registry discovery, never pulls `botpy`, `lark_oapi`,
   or `wecom_aibot_sdk` into `sys.modules`. A base installation therefore starts
   without any channel extra.
2. **Deny by default.** The allowlist unit suite plus each adapter's early-gate
   test, which proves a denied sender is rejected before any side effect
   (media download, reaction, route caching, intake publish), not merely
   dropped at the central intake.
3. **Adapter isolation.** The ChannelManager tests below, plus the two spec
   factories surfacing `ImportError` when their extra is absent.

### Manager isolation semantics

`ChannelManager._init_channels` treats every per-channel failure as local:

| Failure | Behavior |
| --- | --- |
| Factory raises `ImportError` | That channel is disabled with a warning naming the install-mode-correct hint |
| Factory raises anything else | That channel is disabled with an error naming the exception type and message |
| `allow_from` is `[]` | That channel is disabled with an error; it would otherwise drop every inbound message silently |

No case aborts the process. A misconfigured or crashing adapter is disabled;
the remaining channels and the Gateway still start. This replaced an earlier
`SystemExit` on an empty `allow_from`, which let one channel's config error take
down every other channel and the Gateway with it.

## QQ and WeCom Beta contract matrix

Each row is covered independently for both adapters. Test functions live in
`tests/test_channels_qq.py` and `tests/test_channels_wecom.py`.

| Contract row | QQ | WeCom |
| --- | --- | --- |
| Inbound dispatch | `test_on_message_group_dispatch`, `test_on_message_c2c_dispatch` | `test_process_logs_accept_receipt` |
| Inbound dedup | `test_on_message_dedup`, `test_on_message_logs_duplicate_receipt` | `test_process_dedup_skips_repeated_msgid`, `test_process_logs_duplicate_receipt` |
| Allowlist early gate | `test_on_message_disallowed_sender_rejected_before_side_effects` | `test_process_disallowed_sender_skips_download_and_publish` |
| Auth readiness bail-out | `test_start_bails_out_without_credentials` | `test_start_bails_out_without_credentials` |
| Inbound media normalization | `test_attachment_labels_normalize_sdk_metadata`, `test_on_message_attachment_only_still_dispatches` | `test_extract_image_downloads_and_labels`, `test_extract_file_uses_provided_name_over_server_name` |
| Inbound media failure | `test_attachment_labels_absent_or_empty` | `test_extract_image_missing_keys_marks_failed`, `test_extract_image_marks_failed_when_download_returns_no_data` |
| Outbound routing | `test_send_group_routes_to_group_api`, `test_send_c2c_default_route`, `test_send_guild_dm_routes_to_post_dms` | `test_send_replies_with_cached_frame` |
| Outbound media notice | `test_send_media_surfaced_as_notice`, `test_send_media_notice_survives_empty_text` | `test_send_media_surfaced_as_notice` |
| Retryable classification | `test_send_reraises_transient_for_manager_retry`, `test_send_reraises_network_errors` | `test_send_reraises_transient_for_manager_retry` |
| Terminal classification | `test_send_swallows_api_error` | `test_send_swallows_reply_error`, `test_send_logs_no_receipt_when_reply_fails` |
| Malformed inbound | `test_on_message_without_id_is_dropped`, `test_on_message_malformed_event_logs_and_does_not_raise` | `test_process_non_dict_body_is_dropped`, `test_process_missing_sender_falls_back_to_unknown`, `test_process_without_msgid_derives_a_dedup_key`, `test_process_unhandled_error_logs_and_does_not_raise` |
| Missing optional SDK | `test_qq_spec_import_is_cheap`, `test_qq_spec_factory_raises_import_error_without_sdk` | `test_wecom_spec_import_is_cheap`, `test_wecom_spec_factory_raises_import_error_without_sdk` |
| Protocol conformance | `test_qq_satisfies_channel_contract` | `test_wecom_satisfies_channel_contract` |
| Declared maturity | `test_qq_spec_declares_beta_maturity` | `test_wecom_spec_declares_beta_maturity` |

### Observable receipts

Both adapters log the same four receipts, each pinned by wording:

- `<Channel> inbound accepted: ...`
- `<Channel> duplicate event suppressed: ...`
- `<Channel> inbound rejected by allowlist: sender=...`
- `<Channel> message sent: ...`

A swallowed send error must leave no `message sent` receipt behind, so the log
cannot report a delivery that did not happen.

### QQ media boundary

botpy exposes attachment metadata (`content_type`, `filename`) on
`BaseMessage`, so QQ inbound attachments are normalized deterministically into
text labels (`[image: pic.png]`, `[file: doc.pdf]`, `[voice]`). Server-supplied
filenames pass through `safe_name`, so a crafted name cannot smuggle path
components into the Turn text.

The bytes are never fetched. botpy publishes no download helper for the
ephemeral attachment URL, so QQ inbound media is metadata-only, unlike Feishu
and WeCom, whose SDKs expose a download call. Outbound attachments are not
uploaded either: the reply endpoints in use carry markdown text only, so each
dropped file becomes an explicit `[Attachment not sent: <name>]` notice.

## What Beta does not claim

`ChannelSpec.maturity` is the single source for the label shown by
`pico channels list`, `pico channels status`, `pico doctor`, and onboarding.
QQ and WeCom declare `beta`. Feishu declares `live-gated` after its required
V-LF run passed against the real Pico bot on 2026-07-27. An adapter may declare
`live-gated` only in the same change that records a passed live Gate run for a
commit.

Beta means V-C0 and V-S0 pass. It does not claim:

- that a real bot has ever delivered or received a message through Pico on
  that channel;
- that platform quotas, rate limits, credential rotation, or reconnect behavior
  have been observed against the live service;
- that the outbound endpoints behave as the SDK documents them, since every
  outbound assertion here is made against a mocked SDK client.

No fixture, mock, or deterministic run may be reported as a live smoke. Leaving
Beta requires a passed live tracer bullet against a real bot - for Feishu, the
V-LF Gate below: real credentials, a real inbound message, a real outbound
reply, and separately reported deterministic, live, skipped, provider-failure,
and infrastructure results.

## V-LF: real Feishu tracer bullet

### Claim boundary

V-LF proves, for one commit and one recorded scenario, that a real Feishu
message travels the retained production path:

```
Feishu event -> FeishuChannel -> Intake -> Spine -> AgentTurnRunner
  -> AgentLoop -> DeliveryHub -> ChannelOutletAdapter -> Feishu reply
```

Feishu may be described as production-verified only for the exact commit and
scenario captured by a passed V-LF run. A mocked SDK, recorded payload,
`--help` probe, or reachable endpoint never satisfies V-LF.

### Operator-in-the-loop model

Feishu bots cannot message themselves, so the live inbound stimulus is a human
operator. The harness automates everything else: environment isolation,
Gateway lifecycle, log observation, receipt verification, restart
orchestration, evidence classification, and redaction. The harness prints one
instruction per phase and polls observable outcomes with a timeout; an absent
stimulus times out as `inconclusive`, never as a fake pass.

### Environment contract

| Variable | Required | Meaning |
| --- | --- | --- |
| `PICO_LIVE_FEISHU_APP_ID` | yes | Feishu app id for the test bot |
| `PICO_LIVE_FEISHU_APP_SECRET` | yes | Feishu app secret; env-only, never persisted to evidence |
| `PICO_LIVE_FEISHU_OPERATOR_ID` | yes | operator `open_id`; becomes the allowlist and DM target |
| `PICO_LIVE_API_KEY` | yes | Provider key for the Agent Loop (same contract as V-LP) |
| `PICO_LIVE_PROVIDER` / `PICO_LIVE_MODEL` | no | default `deepseek` / `deepseek/deepseek-chat` |
| `PICO_WHEEL` | no | verified V-P0 wheel; when set the Gateway runs from an installed environment |
| `PICO_LIVE_FEISHU_REQUIRED` | set by make | `1` turns skips and timeouts into Gate failures |

`make verify-live-feishu` enables required mode. Ad-hoc
`uv run pytest -m real_channel` keeps missing credentials as ordinary skips.

### Isolation

The harness builds a disposable `PICO_HOME` under a temporary directory:

- `config.json` (mode 0600) enables only the Feishu Channel, sets
  `allow_from=[operator open_id]`, `group_policy="mention"`, and the live
  Provider. Credentials exist only in this temporary file and the
  environment; teardown removes the home.
- The Gateway, Cron store, Session store, media dir, and logs all live under
  this home. The operator's real `~/.pico` is never read or written.
- With `PICO_WHEEL` set, the harness installs the wheel into a fresh
  environment and launches the installed `pico` executable; otherwise it runs
  the checkout via `uv run pico` and records `runtime_source: "checkout"` in
  the report.

### Phases

| Check | Stimulus | Observable outcome |
| --- | --- | --- |
| `gateway_boot` | none | `/health` responds; Feishu websocket start logged |
| `inbound_reply_text` | operator DMs a nonce prompt | inbound accept receipt for the message id; send receipt for the reply; nonce echoed |
| `attachment_inbound` | operator sends one image | media downloaded under the isolated home; Turn completes |
| `media_out` | operator asks the Agent to send a harness-provided file | upload receipt and outbound media send receipt |
| `cron_restart_exactly_once` | harness schedules a one-shot Feishu Cron job, stops the Gateway before the fire time, starts a new Gateway | exactly one claim and one send receipt across both Gateway processes; zero before restart |
| `allowlist_negative_live` | optional second account messages the bot | allowlist reject receipt, no Turn |

`allowlist_negative_live` needs a second Feishu account, so it is optional:
without one it records `skipped` with a reason and does not fail required
mode. Its enforcement remains covered deterministically (see mapping below).

### Acceptance mapping

Issue #21 requires observable outcomes for allowlist, duplicate events,
disconnect/reconnect, and error receipts. V-LF records, per criterion, which
evidence class covers it:

| Criterion | Live evidence | Deterministic evidence (V-C0) |
| --- | --- | --- |
| Real inbound/outbound | `inbound_reply_text` | adapter normalization and outlet tests |
| Allowlist | optional `allowlist_negative_live` | adapter early-gate and Intake tests |
| Duplicate events | none (Feishu redelivers only on failure; not reliably stimulable) | dedup cap and suppression tests |
| Disconnect/reconnect | Gateway restart re-establishes the websocket (`cron_restart_exactly_once` boot logs) | supervised reconnect loop tests |
| Error receipts | any observed send/react failure receipts are recorded | send failure code/msg logging tests |
| Attachment + MediaOut | `attachment_inbound`, `media_out` | media save and outlet MediaOut tests |
| Cron exactly once | `cron_restart_exactly_once` | Cron claim, dedup, restart recompute tests |

A criterion whose live stimulus cannot be produced honestly stays
deterministic-only and is labeled that way in the report; the report never
upgrades deterministic coverage into live evidence.

### Exactly-once design

The Cron phase avoids the claim-TTL trap (a job killed mid-execution is not
reclaimable for 30 minutes): the Gateway is stopped before the job's fire
time, not during execution. Sequence:

1. `pico cron add --at <now+T> --channel feishu --to <operator open_id>`
   against the isolated home while Gateway A runs;
2. stop Gateway A well before `now+T`; assert zero send receipts in A's logs;
3. start Gateway B; the persisted job survives restart
   (`_recompute_next_runs` keeps a future `at` job);
4. assert exactly one claim and one Feishu send receipt in B's logs, and the
   one-shot job is consumed.

### Send receipts

The Feishu adapter logs a structured receipt for every accepted inbound event
and every successful outbound message (message id, message type, no content,
no sender identity). These receipts are the observation points for the
harness and for operators; they are asserted deterministically in
`tests/test_channels_feishu.py`.

### Redaction

Evidence stored under `.pico/evidence/feishu/` is redacted before it is
written:

- open ids, chat ids, and message ids are replaced by `sha256[:12]` digests;
- the app id is replaced by a digest; the app secret and Provider key never
  appear in any evidence file, including on failure paths;
- message bodies are not copied into evidence; the nonce comparison result is
  recorded as a boolean;
- raw Gateway logs stay inside the disposable home and are deleted with it;
  only redacted excerpts enter the evidence directory, each with a recorded
  sha256.

`.pico/` is gitignored; the tracked deliverables are the schema, the
verifier, the rerun command, and the concise index entry - never report
assets.

### Report

`scripts/verify_live_feishu.py` writes
`.pico/evidence/feishu/feishu-live-report.json`:

```json
{
  "schema": "pico.feishu.live.evidence.v1",
  "gate": "V-LF",
  "status": "passed|failed|skipped",
  "live_mode": "required|optional",
  "runtime_source": "installed_wheel|checkout",
  "commit": "<git sha>",
  "checks": {"<phase>": {"status": "...", "evidence_class": "live",
              "receipts": {"...": "sha256:..."}}},
  "criteria": {"<criterion>": {"evidence_class": "live|deterministic|both",
                "check": "<phase or V-C0 reference>"}}
}
```

Exit code 0 requires `status == "passed"`: every required phase passed live.
In required mode a missing credential is a failure; in optional mode it is a
skip that still exits non-zero for automation but is labeled `skipped`.

### Rerun

```bash
export PICO_LIVE_FEISHU_APP_ID=...
export PICO_LIVE_FEISHU_APP_SECRET=...
export PICO_LIVE_FEISHU_OPERATOR_ID=ou_...
export PICO_LIVE_API_KEY=...
make verify-live-feishu
```

## Maintenance

- New Channel-layer deterministic tests join the V-C0 inventory in
  `scripts/verify_channels.py` in the same change.
- A V-LF result binds to one commit; any later Runtime, Channel, or packaging
  change invalidates the claim until the Gate reruns.
- The report schemas version with a `.v2` suffix on breaking change, matching
  the other evidence schemas.
  `pico.channels.evidence` is at `.v2` after the V-S0 bundle split the report
  into `checks.contract` and `checks.security`.
