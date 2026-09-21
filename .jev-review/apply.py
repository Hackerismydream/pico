from pathlib import Path
import hashlib
import shutil
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
payload = Path(sys.argv[2]).resolve()
base = '697499a36c349bd0989344fd0dcd4282d23d33a9'
def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
if git('rev-parse', 'HEAD') != base:
    raise RuntimeError('Feature branch moved; refusing to overwrite it')
subprocess.run(['git', '-C', str(root), 'fetch', 'origin', 'main'], check=True)
if git('rev-parse', 'origin/main') != base:
    raise RuntimeError('Main moved; reconcile before publishing')
expected = {
    'docs/evaluation/jev-personalization.md': '8a7915edb999c8b476f98999724caeb3961c824353d2be13d6b0b37dde6c23fa',
    'docs/plan/jev-personalization.md': 'eb6f63c75ea70f371520178c769bdb2295a26646a0cf06a7020b0cd29ec1d687',
    'pico/agent/personalizer/jev.py': '26c9049fa628c638c7a6d4fa34fc591879204acc629feeee32b28b15a8148e14',
    'pico/agent/personalizer/jev_policy.py': '08b21be688684213416fdc42197f84c18f78a044361f64448c786b93088a918f',
    'pico/config/personalization.py': 'c71f7f1d91fd7e0c76a00b2ec863466c4b4b671c361e5ab34ba468b4fbceb22d',
    'tests/test_personalizer_contract.py': '35d94e9ac663579a22d54dd0942f6830c9646e5925cdce7db44e9d87dd141b75',
    'tests/test_personalizer_jev.py': '46722dda87feb14821de96d0a567244d321d90d1b26711af722c2902ecb31f21',
}
for name, digest in expected.items():
    source = payload / 'product' / name
    if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Payload digest mismatch: ' + name)
    target = root / name
    if target.exists():
        raise RuntimeError('New path already exists: ' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)

def replace(path, old, new, count=1):
    p = root / path
    s = p.read_text()
    if s.count(old) != count:
        raise RuntimeError(f'{path}: expected {count} anchors, got {s.count(old)}: {old[:100]}')
    p.write_text(s.replace(old, new))

replace('pico/config/schema.py',
 'from pico.product import DEFAULT_WORKSPACE_SPEC, get_default_workspace',
 'from pico.config.personalization import PersonalizationGateConfig\nfrom pico.product import DEFAULT_WORKSPACE_SPEC, get_default_workspace')
replace('pico/config/schema.py',
 '    @property\n    def should_warn_deprecated_memory_window',
 '    personalization_gate: PersonalizationGateConfig = Field(default_factory=PersonalizationGateConfig)\n\n    @property\n    def should_warn_deprecated_memory_window')
replace('pico/call_efficiency/models.py',
 '    schema: str = CALL_RECORD_SCHEMA\n',
 '    schema: str = CALL_RECORD_SCHEMA\n    call_id: str | None = None\n    call_kind: str = "chat"\n    duration_ms: float | None = None\n    details: dict[str, Any] = field(default_factory=dict)\n')
replace('pico/call_efficiency/runtime.py','from datetime import datetime, timezone',
 'from copy import deepcopy\nfrom dataclasses import replace\nfrom datetime import datetime, timezone')
replace('pico/call_efficiency/runtime.py','from pico.call_efficiency.models import CallRecord, PreparedCall',
 'from pico.call_efficiency.models import CallRecord, CallUsage, PreparedCall')
replace('pico/call_efficiency/runtime.py','    def close(self) -> None:\n        self.ledger.close()', '''    def record_external(
        self,
        *,
        call_id: str,
        requested_model: str,
        actual_model: str | None,
        raw_usage: Any,
        outcome: str,
        error_category: str | None,
        duration_ms: float,
        session_key: str | None,
        trace_id: str | None,
        turn_span_id: str | None,
        details: dict[str, Any],
    ) -> CallRecord:
        """记录非聊天判断的真实 attempt，不伪造 LLMResponse 或遗漏旁路费用。

        只为已核对版本的 Jev 估价。缺失 usage、未知模型和中途取消不被记成零费用；
        ledger 接受记录不等于持久化成功，实验仍必须检查关闭后的 health 文件。
        """
        raw = raw_usage if isinstance(raw_usage, dict) else {}
        values = [raw.get(key) for key in ("input_tokens", "output_tokens")]
        valid = [type(value) is int and 0 <= value < 2**53 for value in values]
        complete = all(valid)
        input_tokens = values[0] if valid[0] else 0
        output_tokens = values[1] if valid[1] else 0
        usage = CallUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens if complete else None,
            complete=complete,
        )
        findings: list[str] = []
        if not complete:
            findings.append("usage_incomplete")
        if actual_model is None:
            findings.append("actual_model_unknown")
        # TypeSafe Models, checked 2026-09-21: USD 0.042/M input; output is free.
        known_price = actual_model == "jev-1.13.0"
        cost = input_tokens * 0.042 / 1_000_000 if complete and known_price else None
        if not known_price:
            findings.append("pricing_unavailable")
        record = CallRecord(
            requested_model=requested_model,
            attempted_model=requested_model,
            actual_model=actual_model or "unknown",
            accounting_model=actual_model or requested_model,
            usage=usage,
            estimated_cost_usd=cost,
            outcome=outcome,
            finish_reason="decision" if outcome == "success" else "error",
            error_category=error_category,
            session_key=session_key,
            trace_id=trace_id,
            turn_span_id=turn_span_id,
            mode=self.mode,
            cache_policy="not_applicable",
            observed_at=datetime.now(timezone.utc).isoformat(),
            findings=tuple(findings),
            call_id=call_id,
            call_kind="decision",
            duration_ms=duration_ms,
            details={**deepcopy(details), "pricing_version": "typesafe-2026-09-21"},
        )
        if self.mode != "off":
            try:
                self.ledger.append(record)
            except Exception:
                logger.exception("CallEfficiency could not persist an external Call Record")
                return replace(record, findings=(*record.findings, "ledger_write_failed"))
        return record

    def close(self) -> None:
        self.ledger.close()''')
replace('pico/agent/personalizer/personalizer.py','if TYPE_CHECKING:\n',
 'if TYPE_CHECKING:\n    from pico.agent.personalizer.jev import JevPreferenceGate\n')
replace('pico/agent/personalizer/personalizer.py',
 '    def __init__(self, memory: MemoryStore, provider: LLMProvider, model: str):\n',
 '    def __init__(\n        self, memory: MemoryStore, provider: LLMProvider, model: str, *, gate: JevPreferenceGate | None = None\n    ):\n')
replace('pico/agent/personalizer/personalizer.py','        self.model = model\n','        self.model = model\n        self._gate = gate\n')
replace('pico/agent/personalizer/personalizer.py',
 '    async def classify(self, message: str, history: list[dict] | None = None) -> dict:\n',
 '    async def classify(\n        self, message: str, history: list[dict] | None = None, *, allow_gate: bool = False\n    ) -> dict:\n')
replace('pico/agent/personalizer/personalizer.py',
 '        history_text = self._format_history(history) if history else "(no prior context)"\n',
 '''        if allow_gate and self._gate is not None:
            try:
                decision = await self._gate.assess(message, history or [], current_memory or "")
                if decision.fast_pass:
                    return {"needs_clarification": False, "domain": ""}
            except Exception:
                logger.warning("Preference fast path unavailable; retaining the existing classifier")

        history_text = self._format_history(history) if history else "(no prior context)"
''')
replace('pico/agent/personalizer/personalizer.py',
 '            logger.debug("Personalizer.classify: {}", result)\n            return result\n',
 '''            if response.finish_reason == "error" or not isinstance(result, dict):
                return {"needs_clarification": False, "domain": ""}
            needs = result.get("needs_clarification")
            domain = result.get("domain", "")
            if type(needs) is not bool or not isinstance(domain, str) or len(domain) > 128:
                return {"needs_clarification": False, "domain": ""}
            if needs and not domain.strip():
                return {"needs_clarification": False, "domain": ""}
            return {"needs_clarification": needs, "domain": domain.strip() if needs else ""}
''')
replace('pico/agent/loop/main.py','if TYPE_CHECKING:\n    from pico.agent.hook import CompositeHook\n','if TYPE_CHECKING:\n    from pico.agent.hook import CompositeHook\n    from pico.agent.personalizer.jev import JevPreferenceGate\n')
replace('pico/agent/loop/main.py',
 '        self.enable_personalization = False  # 通过 configure_personalization() 设置\n',
 '        self.enable_personalization = False  # 通过 configure_personalization() 设置\n        self._personalization_gate: JevPreferenceGate | None = None\n')
replace('pico/agent/loop/main.py',
 '    def configure_personalization(self, enable: bool) -> None:\n',
 '    def configure_personalization(self, enable: bool, *, gate: JevPreferenceGate | None = None) -> None:\n')
replace('pico/agent/loop/main.py',
 '        self.enable_personalization = bool(enable and self.memory_enabled)\n',
 '        self.enable_personalization = bool(enable and self.memory_enabled)\n        self._personalization_gate = gate if self.enable_personalization else None\n')
replace('pico/agent/loop/main.py',
 '''        # 子智能体结果回注时跳过：其内容是系统生成的通知而非用户输入；个性化处理会污染
        # 用户画像，或针对通知触发澄清。此处仅 SUBAGENT 跳过（不是更宽泛的用户输入集合）：
        # Cron 轮次目前仍会进入并保留该流程。
''',
 '''        # 只有真实用户请求参与偏好学习，系统生成的 Cron 和 Subagent 内容不能更新画像。
''')
replace('pico/agent/loop/main.py',
 '        if self.enable_personalization and origin is not Origin.SUBAGENT:\n',
 '        if self.enable_personalization and req.origin is Origin.USER:\n', count=2)
replace('pico/agent/loop/main.py',
 '            _personalizer = Personalizer(MemoryStore(self.state), self.provider, self.model)\n',
 '            _personalizer = Personalizer(\n                MemoryStore(self.state), self.provider, self.model, gate=self._personalization_gate\n            )\n')
replace('pico/agent/loop/main.py',
 '                _classification = await _personalizer.classify(content, history=_recent)\n',
 '                _classification = await _personalizer.classify(content, history=_recent, allow_gate=not turn_media)\n')
replace('pico/agent/loop/main.py',
 '''            # 子智能体结果回注时跳过（参见上方轮次前流程）：其内容是系统生成的通知，
            # 不是可供学习的用户输入。
''',
 '''            # 与前置分类使用同一 Origin 边界，系统通知不参与用户偏好学习。
''')
replace('pico/cli/_runtime_assembly.py','    from pico.agent.loop import AgentLoop\n',
 '    from pico.agent.loop import AgentLoop\n    from pico.agent.personalizer.jev import JevPreferenceGate\n', count=2)
replace('pico/cli/_runtime_assembly.py',
 '    from pico.agent.loop import AgentLoop\n    from pico.agent.personalizer.jev import JevPreferenceGate\n    from pico.call_efficiency import CallEfficiency, CallEfficiencyProvider\n',
 '    from pico.agent.loop import AgentLoop\n    from pico.call_efficiency import CallEfficiency, CallEfficiencyProvider\n')
replace('pico/cli/_runtime_assembly.py','    call_efficiency: CallEfficiency | None = None\n',
 '    call_efficiency: CallEfficiency | None = None\n    personalization_gate: JevPreferenceGate | None = None\n    _gate_closed: bool = field(default=False, init=False)\n')
replace('pico/cli/_runtime_assembly.py','        self.agent_loop.begin_close()\n',
 '        self.agent_loop.begin_close()\n        if self.personalization_gate is not None:\n            self.personalization_gate.begin_close()\n')
replace('pico/cli/_runtime_assembly.py',
 '        if self.call_efficiency is None:\n',
 '''        if self.personalization_gate is not None and not self._gate_closed:
            try:
                await self.personalization_gate.aclose()
            except Exception:
                logger.exception("preference gate close failed; continuing shutdown")
            except BaseException as exc:
                cancellation = cancellation or exc
            else:
                self._gate_closed = True

        if self.call_efficiency is None:
''')
replace('pico/cli/_runtime_assembly.py',
 '    runtime_provider = CallEfficiencyProvider(provider, call_efficiency)\n',
 '    runtime_provider = CallEfficiencyProvider(provider, call_efficiency)\n    personalization_gate = None\n')
replace('pico/cli/_runtime_assembly.py',
 '''        agent_loop.configure_personalization(
            defaults.enable_personalization,
        )
''',
 '''        gate_config = getattr(defaults, "personalization_gate", None)
        if (
            defaults.enable_personalization
            and backend is not None
            and gate_config is not None
            and gate_config.mode != "off"
        ):
            from pico.agent.personalizer.jev import JevPreferenceGate

            if call_efficiency.mode == "off" or not call_efficiency.ledger.persist:
                raise ValueError("Jev requires persistent CallEfficiency usage tracking")
            personalization_gate = JevPreferenceGate(gate_config, call_efficiency)
            agent_loop.configure_personalization(True, gate=personalization_gate)
        else:
            agent_loop.configure_personalization(defaults.enable_personalization)
''')
replace('pico/cli/_runtime_assembly.py',
 '        call_efficiency=call_efficiency,\n    )\n',
 '        call_efficiency=call_efficiency,\n        personalization_gate=personalization_gate,\n    )\n')
replace('pico/routing/router.py','from __future__ import annotations\n','from __future__ import annotations\n\nimport math\n')
replace('pico/routing/router.py',
 '        try:\n            result = select_model(self._data, classification.category, self._profile)\n',
 '''        if not math.isfinite(classification.similarity) or classification.similarity <= 0:
            logger.warning("Classification supplied no evidence; retaining the configured model")
            return None

        try:
            result = select_model(self._data, classification.category, self._profile)
''')
replace('CONTEXT.md','**Context Builder** (`agent/context/`):', '''**Preference Fast Path** (`agent/personalizer/jev.py`):
An experimental, default-off Personalizer backend that can skip one existing
preference-classification call for a clear new USER request. `shadow` records
without changing the original classifier; `enforce` uses a pinned Jev model,
validated Choice answers and operator-reviewed thresholds. Ambiguity, errors,
media and pending clarifications retain the original path. Runtime Assembly
owns its lifecycle and CallEfficiency records every remote attempt.
_Avoid_: authorization gate, general Decision Engine, or calibrated correctness
claim — none is established by typed answers or configuration.

**Context Builder** (`agent/context/`):''')
replace('Makefile','tests/test_litellm_setup.py -q','tests/test_litellm_setup.py tests/test_personalizer_jev.py tests/test_personalizer_contract.py tests/test_routing_fallback_chain.py -q')
replace('docs/architecture/README.md','- [Canonical Runtime glossary](../../CONTEXT.md)\n','- [Canonical Runtime glossary](../../CONTEXT.md)\n- [Experimental preference fast path](../plan/jev-personalization.md)\n')
p = root / 'docs/evaluation/README.md'
p.write_text(p.read_text() + '''
## Optional preference-triage experiment

The [Jev experiment protocol](jev-personalization.md) defines a default-off,
NOT_RUN comparison against the existing classifier, no pre-classification,
and an ordinary small-model gate. Contract tests do not establish semantic
quality, cost reduction, latency improvement, or positive claim eligibility.
''')
p = root / 'tests/test_routing_fallback_chain.py'
p.write_text(p.read_text() + '''

@pytest.mark.parametrize("similarity", [0.0, -0.1, float("nan"), float("inf"), float("-inf")])
async def test_classifier_without_evidence_retains_default(monkeypatch, similarity):
    from unittest.mock import AsyncMock, MagicMock

    from pico.routing.types import ClassificationResult

    router = ModelRouter(api_key="test")
    router._data = {}
    monkeypatch.setattr(router._classifier, "classify", AsyncMock(return_value=ClassificationResult(category="sanity", similarity=similarity)))
    selector = MagicMock()
    monkeypatch.setattr("pico.routing.router.select_model", selector)
    assert await router.select_model_chain("not a known task") == (None, [])
    selector.assert_not_called()


async def test_real_positive_sanity_classification_still_routes(monkeypatch):
    from unittest.mock import AsyncMock

    from pico.routing.types import ClassificationResult

    router = ModelRouter(api_key="test")
    router._data = {}
    monkeypatch.setattr(router._classifier, "classify", AsyncMock(return_value=ClassificationResult(category="sanity", similarity=0.9)))
    monkeypatch.setattr("pico.routing.router.select_model", lambda *args: _result("a/primary", []))
    assert await router.select_model_chain("hello") == ("a/primary", [])
''')
print('Applied seven digest-verified files and bounded source edits; no live model calls.')
