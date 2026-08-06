.PHONY: help install install-deps lint lint-python lint-tui test test-python test-retained test-tui picobench-smoke picobench picobench-scorecard-estimate picobench-scorecard-ship picobench-scorecard-score picobench-runtime-scheduler picobench-runtime-live-plan picobench-runtime-live-run picobench-runtime-live-verify picobench-codecairn-smoke picobench-codecairn-task-effect-smoke picobench-codecairn-task-effect-estimate picobench-codecairn-task-effect-ship picobench-codecairn-ship verify-codecairn-continuity verify-runtime-hosts verify-live-provider verify-channels verify-live-feishu verify-evolver verify-turn-evidence verify-release build build-tui check-commits check-pr-title check-large-files ci clean

PYTHON ?= python3
PYTHON_LINT_TARGETS ?= scripts/check_commit_file.py scripts/check_commit_messages.py scripts/check_pr_title.py scripts/check_large_files.py scripts/commit_lint.py tests/test_commit_lint.py tests/test_large_file_check.py
COMMIT_RANGE ?= origin/main..HEAD

help:
	@echo "Targets:"
	@echo "  install        Install Python deps, Node deps, and git hooks"
	@echo "  install-deps   Install Python deps only (CI uses this)"
	@echo "  lint           Run Python and TUI lint gates"
	@echo "  lint-python    Ruff-check the current lint target set"
	@echo "  lint-tui       TypeScript lint + RPC drift check"
	@echo "  test           Run focused Python checks and TUI tests"
	@echo "  test-retained  Run the deterministic Python suite without opt-in tests"
	@echo "  picobench-smoke Run the credential-free PicoBench gate"
	@echo "  picobench-runtime-scheduler Run deterministic scheduler A/B experiments"
	@echo "  picobench-runtime-live-plan Freeze the real-Agent scheduler plan and spend ceiling"
	@echo "  picobench-runtime-live-run Run the approved real-Agent scheduler experiment"
	@echo "  picobench-runtime-live-verify Rebuild live scheduler metrics from raw Turn records"
	@echo "  picobench      Run the frozen PicoBench calibration and formal campaign"
	@echo "  picobench-scorecard-estimate Print the current Scorecard worst-case budget"
	@echo "  picobench-scorecard-ship Run the current Context and Tool/MCP Scorecard campaign"
	@echo "  picobench-scorecard-score Compute the multidimensional diagnostic score"
	@echo "  picobench-codecairn-smoke Validate the credential-free CodeCairn Pack"
	@echo "  picobench-codecairn-task-effect-smoke Validate the credential-free task-effect v2 Pack"
	@echo "  picobench-codecairn-task-effect-estimate Print the task-effect v2 worst-case budget"
	@echo "  picobench-codecairn-task-effect-ship Run the frozen task-effect v2 campaign"
	@echo "  picobench-codecairn-ship Run the frozen paid CodeCairn campaign"
	@echo "  verify-codecairn-continuity Run installed Pico-CodeCairn J0-J2"
	@echo "  verify-runtime-hosts Verify CLI, TUI, and Gateway from PICO_WHEEL"
	@echo "  verify-live-provider Run V-LP against one live Provider"
	@echo "  verify-channels Run the deterministic V-C0 contract and V-S0 security Channel gates"
	@echo "  verify-live-feishu Run V-LF, the required real Feishu tracer bullet"
	@echo "  verify-evolver Run the deterministic V-E0 Evolver gate"
	@echo "  verify-turn-evidence Run the deterministic V-TE0 turn-correlation gate"
	@echo "  verify-release Run V-R0, the release candidate gate over every layer"
	@echo "  check-commits  Validate Conventional Commit subjects"
	@echo "  check-pr-title Validate the PR title in PR_TITLE"
	@echo "  check-large-files Validate PR files avoid blocked assets and size bloat"
	@echo "  ci             Run the local CI gate"
	@echo "  clean          Remove generated caches and build output"

install-deps:
	uv sync --frozen --extra dev --dev

install: install-deps
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg
	npm ci
	npm ci --prefix ui-tui

lint: lint-python lint-tui

lint-python:
	uv run --extra dev ruff check $(PYTHON_LINT_TARGETS)
	uv run --extra dev ruff format --check $(PYTHON_LINT_TARGETS)

lint-tui:
	npm run lint --prefix ui-tui
	npm run lint:rpc --prefix ui-tui
	npm run lint:rpc-surface --prefix ui-tui
	npm run type-check --prefix ui-tui

test: test-python test-tui

test-python:
	uv run --extra dev pytest tests/test_commit_lint.py tests/test_large_file_check.py tests/test_cli_smoke.py tests/test_litellm_setup.py -q

test-retained:
	uv run --frozen --all-extras --exact pytest tests -q --strict-markers -m 'not (real_llm or llm_judge or real_vm or real_channel or external_runtime or e2e)'

picobench-smoke:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench --mode smoke

picobench:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench --mode ship

picobench-scorecard-estimate:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.scorecard_campaign estimate

picobench-scorecard-ship:
	@test -n "$$PICO_SCORECARD_RUNTIME_EVIDENCE" || (echo "PICO_SCORECARD_RUNTIME_EVIDENCE is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.scorecard_campaign ship \
		--runtime-evidence "$$PICO_SCORECARD_RUNTIME_EVIDENCE"

picobench-scorecard-score:
	@test -n "$$PICO_SCORECARD_FORMAL_SUMMARY" || (echo "PICO_SCORECARD_FORMAL_SUMMARY is required" >&2; exit 2)
	@test -n "$$PICO_SCORECARD_RUNTIME_EVIDENCE" || (echo "PICO_SCORECARD_RUNTIME_EVIDENCE is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.scorecard \
		--formal-summary "$$PICO_SCORECARD_FORMAL_SUMMARY" \
		--runtime-evidence "$$PICO_SCORECARD_RUNTIME_EVIDENCE"

picobench-runtime-scheduler:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.runtime.scheduler_experiments

picobench-runtime-live-plan:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.runtime.live_scheduler_experiment plan

picobench-runtime-live-run:
	@test -n "$$PICO_LIVE_PERF_APPROVAL_DIGEST" || (echo "PICO_LIVE_PERF_APPROVAL_DIGEST is required" >&2; exit 2)
	@test -n "$$PICO_LIVE_PERF_APPROVED_CNY" || (echo "PICO_LIVE_PERF_APPROVED_CNY is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.runtime.live_scheduler_experiment run \
			--approval-digest "$$PICO_LIVE_PERF_APPROVAL_DIGEST" \
			--approved-cny "$$PICO_LIVE_PERF_APPROVED_CNY"

picobench-runtime-live-verify:
	@test -n "$$PICO_LIVE_PERF_EVIDENCE" || (echo "PICO_LIVE_PERF_EVIDENCE is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.runtime.live_scheduler_experiment verify \
			--evidence "$$PICO_LIVE_PERF_EVIDENCE"

picobench-codecairn-smoke:
	uv run --frozen --all-extras --exact pytest \
		tests/test_picobench_codecairn_memory.py \
		tests/test_verify_codecairn_continuity.py \
		-q --strict-markers

picobench-codecairn-task-effect-smoke:
	uv run --frozen --all-extras --exact pytest \
		tests/test_picobench_codecairn_memory.py \
		tests/integration/test_picobench_codecairn_task_effect_e2e.py \
		tests/test_picobench_contract.py \
		tests/test_picobench_reporting.py \
		-q --strict-markers

picobench-codecairn-task-effect-estimate:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.codecairn_task_effect_campaign estimate

picobench-codecairn-task-effect-ship:
	@test -n "$$PICO_TASK_EFFECT_PICO_WHEEL" || (echo "PICO_TASK_EFFECT_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_TASK_EFFECT_CODECAIRN_WHEEL" || (echo "PICO_TASK_EFFECT_CODECAIRN_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_TASK_EFFECT_STAGE_C_SUMMARY" || (echo "PICO_TASK_EFFECT_STAGE_C_SUMMARY is required" >&2; exit 2)
	@test -n "$$PICO_TASK_EFFECT_AUTHORIZATION" || (echo "PICO_TASK_EFFECT_AUTHORIZATION is required" >&2; exit 2)
	@test -n "$$PICO_TASK_EFFECT_CAMPAIGN_OUTPUT" || (echo "PICO_TASK_EFFECT_CAMPAIGN_OUTPUT is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.codecairn_task_effect_campaign ship \
		--output-root "$$PICO_TASK_EFFECT_CAMPAIGN_OUTPUT"

picobench-codecairn-ship:
	@test -n "$$PICO_CODECAIRN_PICO_WHEEL" || (echo "PICO_CODECAIRN_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_WHEEL" || (echo "PICO_CODECAIRN_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_PAIR_MANIFEST" || (echo "PICO_CODECAIRN_PAIR_MANIFEST is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_CONTINUITY_SUMMARY" || (echo "PICO_CODECAIRN_CONTINUITY_SUMMARY is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_CAMPAIGN_OUTPUT" || (echo "PICO_CODECAIRN_CAMPAIGN_OUTPUT is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python scripts/run_codecairn_campaign.py \
		--mode ship \
		--output-root "$$PICO_CODECAIRN_CAMPAIGN_OUTPUT"

verify-codecairn-continuity:
	@test -n "$$PICO_CODECAIRN_PICO_WHEEL" || (echo "PICO_CODECAIRN_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_WHEEL" || (echo "PICO_CODECAIRN_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_PICO_HANDOFF" || (echo "PICO_CODECAIRN_PICO_HANDOFF is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_HANDOFF" || (echo "PICO_CODECAIRN_HANDOFF is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_IMPLEMENTATION_PICO_WHEEL" || (echo "PICO_CODECAIRN_IMPLEMENTATION_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_COMPATIBILITY_PICO_WHEEL" || (echo "PICO_CODECAIRN_COMPATIBILITY_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_PICO_DISTRIBUTION_REPORT" || (echo "PICO_CODECAIRN_PICO_DISTRIBUTION_REPORT is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_COMMIT" || (echo "PICO_CODECAIRN_COMMIT is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_SOURCE_ROOT" || (echo "PICO_CODECAIRN_SOURCE_ROOT is required" >&2; exit 2)
	@test -n "$$PICO_CODECAIRN_OUTPUT_ROOT" || (echo "PICO_CODECAIRN_OUTPUT_ROOT is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python scripts/verify_codecairn_continuity.py \
		--pico-wheel "$$PICO_CODECAIRN_PICO_WHEEL" \
		--codecairn-wheel "$$PICO_CODECAIRN_WHEEL" \
		--pico-handoff "$$PICO_CODECAIRN_PICO_HANDOFF" \
		--codecairn-handoff "$$PICO_CODECAIRN_HANDOFF" \
		--pico-implementation-wheel "$$PICO_CODECAIRN_IMPLEMENTATION_PICO_WHEEL" \
		--pico-compatibility-wheel "$$PICO_CODECAIRN_COMPATIBILITY_PICO_WHEEL" \
		--pico-distribution-report "$$PICO_CODECAIRN_PICO_DISTRIBUTION_REPORT" \
		--pico-commit "$$PICO_CODECAIRN_COMMIT" \
		--pico-source-root "$$PWD" \
		--codecairn-source-root "$$PICO_CODECAIRN_SOURCE_ROOT" \
		--output-root "$$PICO_CODECAIRN_OUTPUT_ROOT"

test-tui:
	npm test --prefix ui-tui

verify-runtime-hosts:
	@test -n "$$PICO_WHEEL" || (echo "PICO_WHEEL is required" >&2; exit 2)
	uv run --frozen --all-extras --exact pytest \
		tests/integration/test_runtime_hosts_real_llm.py::test_runtime_hosts_from_installed_wheel \
		-q -m external_runtime --strict-markers -rs

verify-live-provider:
	@test -n "$$PICO_WHEEL" || (echo "PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_LIVE_API_KEY" || (echo "PICO_LIVE_API_KEY is required" >&2; exit 2)
	PICO_LIVE_REQUIRED=1 uv run --frozen --all-extras --exact pytest \
		tests/integration/test_runtime_hosts_real_llm.py::test_runtime_hosts_real_llm \
		-q -m real_llm --strict-markers -rs

verify-channels:
	uv run --frozen --all-extras --exact python scripts/verify_channels.py \
		--output-root .pico/evidence/channels

verify-live-feishu:
	@test -n "$$PICO_LIVE_FEISHU_APP_ID" || (echo "PICO_LIVE_FEISHU_APP_ID is required" >&2; exit 2)
	@test -n "$$PICO_LIVE_FEISHU_APP_SECRET" || (echo "PICO_LIVE_FEISHU_APP_SECRET is required" >&2; exit 2)
	@test -n "$$PICO_LIVE_FEISHU_OPERATOR_ID" || (echo "PICO_LIVE_FEISHU_OPERATOR_ID is required" >&2; exit 2)
	@test -n "$$PICO_LIVE_API_KEY" || (echo "PICO_LIVE_API_KEY is required" >&2; exit 2)
	PICO_LIVE_FEISHU_REQUIRED=1 uv run --frozen --all-extras --exact python scripts/verify_live_feishu.py \
		--output-root .pico/evidence/feishu

verify-turn-evidence:
	uv run --frozen --all-extras --exact python scripts/verify_turn_evidence.py \
		--output-root .pico/evidence/turns

verify-release:
	uv run --frozen --all-extras --exact python scripts/verify_release.py \
		--output-root .pico/evidence/release

verify-evolver:
	uv run --frozen --all-extras --exact pytest \
		tests/test_cli_evolve_commands.py \
		tests/test_evolver_*.py \
		tests/test_appworld_precheck.py \
		tests/test_appworld_sandbox.py \
		tests/integration/test_evolver_lifecycle_e2e.py \
		-q --strict-markers

build: build-tui

build-tui:
	npm run build --prefix ui-tui

check-commits:
	npx commitlint --from origin/main --to HEAD --config commitlint.config.cjs
	PYTHONPATH=. uv run --extra dev python scripts/check_commit_messages.py $(COMMIT_RANGE)

check-pr-title:
	PYTHONPATH=. uv run --extra dev python scripts/check_pr_title.py

check-large-files:
	PYTHONPATH=. uv run --extra dev python scripts/check_large_files.py $(COMMIT_RANGE)

ci: lint test build

clean:
	rm -rf .pytest_cache .ruff_cache .uv-cache .mypy_cache htmlcov dist build
	rm -rf ui-tui/dist ui-tui/coverage ui-tui/.vitest-cache ui-tui/packages/hermes-ink/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
