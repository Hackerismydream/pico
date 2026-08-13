.PHONY: help install install-deps format check lint lint-python lint-tui test test-python test-retained test-tui picobench-smoke picobench picobench-reproduce picobench-scorecard-estimate picobench-scorecard-ship picobench-scorecard-score picobench-runtime-scheduler picobench-runtime-tools picobench-runtime-live-plan picobench-runtime-live-run picobench-runtime-live-verify picobench-call-efficiency-plan picobench-call-efficiency-preflight picobench-call-efficiency-run picobench-call-efficiency-verify picobench-tracing-plan picobench-tracing-run picobench-tracing-verify picobench-myna-task-effect-plan picobench-myna-task-effect-run picobench-myna-task-effect-verify picobench-memory-agent-plan picobench-memory-agent-run picobench-memory-agent-verify verify-myna-integration verify-runtime-hosts verify-live-provider verify-channels verify-live-feishu verify-evolver verify-turn-evidence verify-release build build-tui check-commits check-pr-title check-large-files ci clean

PYTHON ?= python3
PYTHON_LINT_TARGETS ?= scripts/check_commit_file.py scripts/check_commit_messages.py scripts/check_pr_title.py scripts/check_large_files.py scripts/commit_lint.py tests/test_commit_lint.py tests/test_large_file_check.py
COMMIT_RANGE ?= origin/main..HEAD
PICO_MYNA_TASK_EFFECT_KIND ?= calibration
PICO_MYNA_TASK_EFFECT_REPETITIONS ?= $(if $(filter formal,$(PICO_MYNA_TASK_EFFECT_KIND)),3,2)
PICO_MYNA_TASK_EFFECT_CORPUS := benchmarks/picobench/tasks/myna_task_effect/$(PICO_MYNA_TASK_EFFECT_KIND).json
PICO_MYNA_TASK_EFFECT_OUTPUT ?= .pico/evidence/myna-task-effect/$(PICO_MYNA_TASK_EFFECT_KIND)
PICO_MEMORY_AGENT_CORPUS := benchmarks/picobench/tasks/myna_task_effect/agent.json
PICO_MEMORY_AGENT_OUTPUT ?= .pico/evidence/myna-task-effect/agent
PICO_CALL_EFFICIENCY_OUTPUT ?= .pico/evidence/call-efficiency-cost-current
PICO_TRACING_OUTPUT ?= .pico/evidence/tracing-overhead-current

help:
	@echo "Targets:"
	@echo "  install        Install Python deps, Node deps, and git hooks"
	@echo "  install-deps   Install Python deps only (CI uses this)"
	@echo "  format         Format Python sources"
	@echo "  check          Run the complete local deterministic acceptance gate"
	@echo "  lint           Run Python and TUI lint gates"
	@echo "  lint-python    Ruff-check the current lint target set"
	@echo "  lint-tui       TypeScript lint + RPC drift check"
	@echo "  test           Run focused Python checks and TUI tests"
	@echo "  test-retained  Run the deterministic Python suite without opt-in tests"
	@echo "  picobench-smoke Run the credential-free PicoBench gate"
	@echo "  picobench-runtime-scheduler Run deterministic scheduler A/B experiments"
	@echo "  picobench-runtime-tools Run the Tool scheduler A/B microbenchmark"
	@echo "  picobench-runtime-live-plan Freeze the real-Agent scheduler plan and spend ceiling"
	@echo "  picobench-runtime-live-run Run the approved real-Agent scheduler experiment"
	@echo "  picobench-runtime-live-verify Rebuild live scheduler metrics from raw Turn records"
	@echo "  picobench-call-efficiency-plan Freeze the current integrated cost campaign plan"
	@echo "  picobench-call-efficiency-preflight Verify live DeepSeek prompt-cache behavior"
	@echo "  picobench-call-efficiency-run Run or resume the approved 72-Trial cost campaign"
	@echo "  picobench-call-efficiency-verify Rebuild cost evidence without Provider calls"
	@echo "  picobench-tracing-plan Print the 1,000-pair Runtime tracing plan"
	@echo "  picobench-tracing-run Run or resume the deterministic tracing on/off campaign"
	@echo "  picobench-tracing-verify Rebuild tracing metrics and verify raw trace receipts"
	@echo "  picobench-myna-task-effect-plan Freeze the installed Pico x Myna A/B plan"
	@echo "  picobench-myna-task-effect-run Run or resume the credential-free A/B"
	@echo "  picobench-myna-task-effect-verify Reinstall candidates and rebuild A/B evidence"
	@echo "  picobench-memory-agent-plan Freeze the lightweight real-Agent Memory A/B"
	@echo "  picobench-memory-agent-run Run or resume the approved 48-Trial Agent A/B"
	@echo "  picobench-memory-agent-verify Rebuild Agent A/B metrics without Provider calls"
	@echo "  picobench      Run the frozen PicoBench calibration and formal campaign"
	@echo "  picobench-reproduce Run or reuse every Scorecard track and render one report"
	@echo "  picobench-scorecard-estimate Print the current Scorecard worst-case budget"
	@echo "  picobench-scorecard-ship Run the current Context and Tool/MCP Scorecard campaign"
	@echo "  picobench-scorecard-score Compute the multidimensional diagnostic score"
	@echo "  verify-myna-integration Verify installed Pico and Myna wheels in Python 3.12"
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

format:
	uv run --extra dev ruff format pico scripts tests

check: lint test-retained test-tui build

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

picobench-reproduce:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.reproduce

picobench-scorecard-estimate:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.scorecard_campaign estimate

picobench-scorecard-ship:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.scorecard_campaign ship \
		$(if $(PICO_SCORECARD_RUNTIME_EVIDENCE),--runtime-evidence "$(PICO_SCORECARD_RUNTIME_EVIDENCE)",)

picobench-scorecard-score:
	@test -n "$$PICO_SCORECARD_FORMAL_SUMMARY" || (echo "PICO_SCORECARD_FORMAL_SUMMARY is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.scorecard \
		--formal-summary "$$PICO_SCORECARD_FORMAL_SUMMARY" \
		$(if $(PICO_SCORECARD_RUNTIME_EVIDENCE),--runtime-evidence "$(PICO_SCORECARD_RUNTIME_EVIDENCE)",) \
		$(if $(PICO_SCORECARD_TOKENWISE_REPORT),--tokenwise-report "$(PICO_SCORECARD_TOKENWISE_REPORT)",) \
		$(if $(PICO_SCORECARD_PREREGISTERED),--scoring-spec-preregistered,)

picobench-runtime-scheduler:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.runtime.scheduler_experiments

picobench-runtime-tools:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.runtime.tool_execution_experiments

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

picobench-call-efficiency-plan picobench-call-efficiency-preflight picobench-call-efficiency-run picobench-call-efficiency-verify:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.tokenwise_cost_campaign \
		--mode $(if $(filter picobench-call-efficiency-run,$@),formal,$(patsubst picobench-call-efficiency-%,%,$@)) \
		--output-root "$(PICO_CALL_EFFICIENCY_OUTPUT)" \
		$(if $(filter picobench-call-efficiency-preflight picobench-call-efficiency-run,$@),--execute-paid-campaign,)

picobench-tracing-plan picobench-tracing-run picobench-tracing-verify:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.tracing.overhead_experiment \
		$(patsubst picobench-tracing-%,%,$@) \
		--output-root "$(PICO_TRACING_OUTPUT)" \
		$(if $(PICO_TRACING_COMMIT),--pico-commit "$(PICO_TRACING_COMMIT)",)

picobench-myna-task-effect-plan picobench-myna-task-effect-run picobench-myna-task-effect-verify:
	@test "$(PICO_MYNA_TASK_EFFECT_KIND)" = "calibration" -o "$(PICO_MYNA_TASK_EFFECT_KIND)" = "formal" || (echo "PICO_MYNA_TASK_EFFECT_KIND must be calibration or formal" >&2; exit 2)
	@test -n "$$PICO_MYNA_PICO_WHEEL" || (echo "PICO_MYNA_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_WHEEL" || (echo "PICO_MYNA_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_PICO_COMMIT" || (echo "PICO_MYNA_PICO_COMMIT is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_COMMIT" || (echo "PICO_MYNA_COMMIT is required" >&2; exit 2)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.myna_task_effect.campaign \
		$(patsubst picobench-myna-task-effect-%,%,$@) \
		--corpus "$(PICO_MYNA_TASK_EFFECT_CORPUS)" \
		--output-root "$(PICO_MYNA_TASK_EFFECT_OUTPUT)" \
		--pico-wheel "$$PICO_MYNA_PICO_WHEEL" \
		--myna-wheel "$$PICO_MYNA_WHEEL" \
		--pico-commit "$$PICO_MYNA_PICO_COMMIT" \
		--myna-commit "$$PICO_MYNA_COMMIT" \
		--repetitions "$(PICO_MYNA_TASK_EFFECT_REPETITIONS)"

picobench-memory-agent-plan picobench-memory-agent-run:
	@test -n "$$PICO_MYNA_PICO_WHEEL" || (echo "PICO_MYNA_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_WHEEL" || (echo "PICO_MYNA_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_PICO_COMMIT" || (echo "PICO_MYNA_PICO_COMMIT is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_COMMIT" || (echo "PICO_MYNA_COMMIT is required" >&2; exit 2)
	$(if $(filter picobench-memory-agent-run,$@),@test "$$PICO_BENCH_EXECUTE_PAID" = "1" || (echo "PICO_BENCH_EXECUTE_PAID=1 is required" >&2; exit 2),)
	$(if $(filter picobench-memory-agent-run,$@),@test -n "$$PICO_MEMORY_AGENT_APPROVAL_DIGEST" || (echo "PICO_MEMORY_AGENT_APPROVAL_DIGEST is required" >&2; exit 2),)
	$(if $(filter picobench-memory-agent-run,$@),@test -n "$$PICO_MEMORY_AGENT_APPROVED_CNY" || (echo "PICO_MEMORY_AGENT_APPROVED_CNY is required" >&2; exit 2),)
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.myna_task_effect.agent_campaign \
		$(patsubst picobench-memory-agent-%,%,$@) \
		--corpus "$(PICO_MEMORY_AGENT_CORPUS)" \
		--output-root "$(PICO_MEMORY_AGENT_OUTPUT)" \
		--pico-wheel "$$PICO_MYNA_PICO_WHEEL" \
		--myna-wheel "$$PICO_MYNA_WHEEL" \
		--pico-commit "$$PICO_MYNA_PICO_COMMIT" \
		--myna-commit "$$PICO_MYNA_COMMIT" \
		$(if $(filter picobench-memory-agent-run,$@),--approval-digest "$$PICO_MEMORY_AGENT_APPROVAL_DIGEST" --approved-cny "$$PICO_MEMORY_AGENT_APPROVED_CNY",)

picobench-memory-agent-verify:
	uv run --frozen --all-extras --exact python -m benchmarks.picobench.packs.myna_task_effect.agent_campaign \
		verify \
		--corpus "$(PICO_MEMORY_AGENT_CORPUS)" \
		--output-root "$(PICO_MEMORY_AGENT_OUTPUT)"

verify-myna-integration:
	@test -n "$$PICO_MYNA_PICO_WHEEL" || (echo "PICO_MYNA_PICO_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_WHEEL" || (echo "PICO_MYNA_WHEEL is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_SOURCE_ROOT" || (echo "PICO_MYNA_SOURCE_ROOT is required" >&2; exit 2)
	@test -n "$$PICO_MYNA_WHEEL_SHA256" || (echo "PICO_MYNA_WHEEL_SHA256 is required" >&2; exit 2)
	@tmp=$$(mktemp -d); \
	trap 'rm -rf "$$tmp"' EXIT; \
	uv venv --python 3.12 "$$tmp/venv"; \
	uv pip install --python "$$tmp/venv/bin/python" "$$PICO_MYNA_PICO_WHEEL" "$$PICO_MYNA_WHEEL"; \
	cd "$$tmp"; \
	"$$tmp/venv/bin/python" "$(CURDIR)/scripts/verify_myna_integration.py" \
		--pico-wheel "$$PICO_MYNA_PICO_WHEEL" \
		--myna-wheel "$$PICO_MYNA_WHEEL" \
		--source-root "$(CURDIR)" \
		--myna-source-root "$$PICO_MYNA_SOURCE_ROOT" \
		--myna-sha256 "$$PICO_MYNA_WHEEL_SHA256"

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
