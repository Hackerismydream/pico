import asyncio
import re
from pathlib import Path

from benchmarks.picobench.canonical import canonical_json
from benchmarks.picobench.packs.runtime.live_scheduler_experiment import (
    LiveSchedulerConfig,
    _live_work,
    _run_live_arm,
    build_live_scheduler_plan,
)
from pico.config.schema import Config
from pico.providers.base import LLMProvider, LLMResponse


class _MarkerProvider(LLMProvider):
    def get_default_model(self) -> str:
        return "fake/live-agent"

    async def chat(self, messages, **kwargs) -> LLMResponse:
        markers = re.findall(r"PICO_LIVE_PERF_R\d{2}_(?:HOT|FG)_\d{2}", str(messages[-1]["content"]))
        marker = markers[-1]
        await asyncio.sleep(0.002 if "_HOT_" in marker else 0.001)
        return LLMResponse(
            content=marker,
            model="fake/live-agent",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


def _small_config() -> LiveSchedulerConfig:
    return LiveSchedulerConfig(
        repetitions=1,
        user_slots=2,
        hot_turns=1,
        foreground_sessions=3,
        hard_cap_cny=0.2,
    )


def test_live_plan_freezes_workload_and_budget_without_credentials() -> None:
    config = LiveSchedulerConfig()
    plan = build_live_scheduler_plan(
        config,
        repository_root=Path(__file__).resolve().parents[1],
        provider_name="deepseek",
        model="deepseek/deepseek-v4-flash",
    )

    assert config.planned_turns == 156
    assert config.maximum_provider_request_attempts == 312
    assert config.maximum_cost_cny < config.hard_cap_cny == 2.0
    assert plan["budget"]["planned_turns"] == 156
    assert "api_key" not in canonical_json(plan).lower()


async def test_live_arm_runs_real_agent_loop_with_marker_verification(tmp_path) -> None:
    config = _small_config()
    base = Config()
    base.agents.defaults.model = "fake/live-agent"
    work = _live_work(config, 0)

    result = await _run_live_arm(
        config,
        work=work,
        scheduler_kind="session_lanes",
        base_config=base,
        provider=_MarkerProvider(),
        workspace=tmp_path,
    )

    assert result["accepted_requests"] == 4
    assert result["measured_foreground_requests"] == 3
    assert result["task_failures"] == 0
    assert result["runner_exceptions"] == 0
    assert result["total_tokens"] == 60
