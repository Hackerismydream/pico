# Pico 上下文治理系统：设计、测试与验证

## 1. 设计哲学

Pico 的上下文治理不是"撑不住时做一次摘要"的应急手段，而是一套**持续维护机制**：

- 低压时用 deterministic 手段（预算裁剪、历史替换、工具输出缩略）持续控制 prompt 大小；
- 高压时主动调用 LLM 生成面向任务继续执行的结构化 handoff summary；
- 每次决策都可追溯（trace event + report + budget summary）；
- 成本可量化（compact 调用自身的 token 也算在净收益里）。

核心原则：**压缩服务于继续执行，不是服务于节省空间。**

---

## 2. 架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│                          Engine.run_turn()                       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              ContextOrchestrator.build()                  │   │
│  │                                                          │   │
│  │  1. ContextManager.build(request)                        │   │
│  │     ├── SectionPolicies (prefix/memory/skills/history)   │   │
│  │     ├── BudgetReduction (overflow → trim in order)       │   │
│  │     └── TurnHistoryBuilder (retention + replacements)    │   │
│  │                                                          │   │
│  │  2. ContextUsageAnalyzer.analyze(rendered)               │   │
│  │     ├── Token estimation (chars / 4)                     │   │
│  │     ├── Pressure ratio = tokens / context_window         │   │
│  │     └── Pressure tier classification                     │   │
│  │                                                          │   │
│  │  3. Compaction decision (_compact_request)               │   │
│  │     ├── prompt_over_budget → deterministic compact       │   │
│  │     ├── tier3_summary + delta≥4 → LLM handoff compact   │   │
│  │     └── otherwise → no compaction                        │   │
│  │                                                          │   │
│  │  4. If compact: CompactManager.compact(summary_mode)     │   │
│  │     ├── plan() → boundary, delta, protected             │   │
│  │     ├── LLM mode → HandoffAdapter → complete_model()    │   │
│  │     ├── Failure → deterministic fallback                 │   │
│  │     └── Rebuild prompt after compaction                  │   │
│  │                                                          │   │
│  │  5. Emit events + attach metadata                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  complete_model(prompt, max_new_tokens) → ModelResult            │
│  Parse response → execute tools → loop                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块职责

| 模块 | 行数 | 职责 |
|------|------|------|
| `context_manager.py` | 337 | Section 组装、预算裁剪、prompt 渲染 |
| `context_orchestrator.py` | 200 | 决策中枢：何时 compact、用什么 mode、emit 事件 |
| `context_handoff.py` | 232 | LLM handoff：prompt 模板、解析器、adapter、渲染 |
| `compact.py` | 247 | 压缩执行：plan/compact/deterministic text/LLM 分支 |
| `context_pressure.py` | 114 | 压力计算：ratio、tier、identity 匹配 |
| `context_usage.py` | 110 | Token 估算、模型窗口识别、usage 分析 |
| `context_sections.py` | 106 | Section 政策注册、预算值、裁剪优先级 |
| `context_report.py` | 101 | 构建 prompt metadata report |
| `context_retention.py` | 69 | Tool 保留策略（inline vs stub） |
| `context_replacements.py` | 148 | 替换缓存 ledger（避免重复压缩同一内容） |
| `context_budget_summary.py` | 120 | 汇总 evidence：usage、compact cost、净收益 |

---

## 4. 压力分层

| Tier | 压力比 | 行为 |
|------|--------|------|
| `tier0_observe` | < 60% | 不做任何压缩，正常组装 |
| `tier1_snip` | 60%–80% | Section 预算裁剪开始生效 |
| `tier2_prune` | 80%–95% | 更激进的历史压缩（替换 ledger 活跃） |
| `tier3_summary` | ≥ 95% | 主动触发 LLM handoff compact |

**压力比计算：**
```
pressure_ratio = total_estimated_tokens / context_window
estimated_tokens = sum(section_chars) / 4
```

**校准机制：** 如果上一次 completion 的 provider identity（model + base_url + cache_key）与当前一致，用 actual tokens 替代估算值。

---

## 5. Compaction 双模式

### 5.1 Deterministic（默认）

触发条件：`prompt_over_budget`（char budget 超 60,000）

行为：
- 从 delta items 提取：最后一条 user request、最后一条 assistant note、files read/modified
- 生成固定格式文本（`"Compacted session summary:"` 开头）
- 如有 prior summary，增量拼接

优点：零额外成本、确定性、可回滚
缺点：丢失上下文细节（变量名、错误信息、决策推理）

### 5.2 LLM Handoff（Phase 1 新增）

触发条件：`tier3_summary` + delta ≥ 4 events + 非 prompt_over_budget

行为：
1. `render_delta_for_handoff(delta_items)` → 构建 LLM 输入（per-item 截断，总计 ≤ 20k chars）
2. `HandoffAdapter.generate()` → 调用 `complete_model()` 生成结构化摘要
3. `HandoffParser.parse()` → 提取 Goal/Constraints/Files/Decisions/Blockers/NextSteps
4. 验证 `goal` 和 `next_steps` 非空
5. 如成功：`render_handoff_summary()` → 存入 session
6. 如失败（exception / parse failure）：回退 deterministic

**Handoff Summary 结构：**
```markdown
## Goal
<用户要完成什么>

## Constraints
- <用户约束>

## Files Read
- <读过的文件路径>

## Files Modified
- <改过的文件路径>

## Key Decisions
- <关键决策>

## Blockers
- <当前阻塞>

## Next Steps
- <下一步应该做什么>
```

**Fallback 保证：**
- `complete_model()` 抛异常 → 返回 None → deterministic
- LLM 返回无法解析的文本 → `goal == ""` → 返回 None → deterministic
- usage metadata 异常（非数字、负数）→ `_optional_int()` 归零，不影响主流程

---

## 6. Section 预算与裁剪

### 默认预算（chars）

| Section | Budget | Floor | 裁剪顺序 |
|---------|--------|-------|----------|
| prefix | 12,000 | 4,000 | 第 5 |
| memory | 8,000 | 1,200 | 第 4 |
| skills | 4,000 | 600 | 第 2 |
| relevant_memory | 6,000 | 1,000 | 第 1（最先裁） |
| history | 30,000 | 6,000 | 第 3 |
| current_request | 无限 | 无限 | 永不裁 |

**Total budget:** 60,000 chars

**裁剪逻辑：** 如果 prompt 超 total_budget，按 reduction_rank 顺序依次裁剪每个 section 直到 fit。每个 section 不会裁到低于 floor。

---

## 7. 替换缓存 Ledger

解决问题：相同文件内容在多轮中反复出现，每次都重新渲染浪费 chars。

机制：
- 首次遇到大型 tool output → 生成 stub（`"read_file output: artifact_ref_123 (15000 chars)"`）
- 计算 `content_sha256`，存入 `session["context_replacements"]`
- 下次相同 event_id + 相同 hash → 直接复用 stub（cache hit）
- 如果 hash 变了（文件被修改）→ 作废旧 stub，重新渲染

**保护规则：**
- Protected tools（ask_user, agent, send_message）永不被替换
- 失败的 tool calls 永不被替换
- 最近 N turns 的 tool calls 永不被替换
- 涉及当前任务 changed_paths 的 tool calls 永不被替换

---

## 8. 成本追踪

### 主请求成本

```python
cost = (uncached_input * input_rate + cached_input * cached_rate + output * output_rate) / 1M
```

默认 proxy pricing：input $2/M, cached $0.2/M, output $8/M

### Compact 调用成本

LLM handoff compact 自身也是一次 model call，其 usage 单独记录：

```python
compact_call_usage = {
    "input_tokens": N,
    "output_tokens": N,
    "total_tokens": N,
    "cached_tokens": N,
    "model": "...",
    "provider": "...",
}
```

### 净收益计算

```
net_benefit = pre_compact_estimated_tokens - post_compact_estimated_tokens - compact_call_total_tokens
```

- 正值 = compact 有效，主请求节省超过 compact 自身花费
- 负值 = compact 花费超过收益（暴露出来，不 clamp）
- `compact_call_usage` 不持久化到 session（`_persistent_summary()` 主动剥离）

---

## 9. 事件与可观测性

每次 context build 产生的事件链：

```
context_orchestrator_decision
├── pressure_tier
├── compact_trigger (null | "auto_tier3_summary" | "auto_prompt_over_budget")
├── summary_mode ("" | "deterministic" | "llm" | "deterministic_fallback")
├── compact_call_usage
├── pre_compact_estimated_tokens
└── post_compact_estimated_tokens

compaction_created (仅当 compact 发生)
├── trigger
├── summary_mode
├── pre_tokens / post_tokens
├── delta_event_count
└── compact_call_usage

context_usage_recorded
├── pressure_tier
├── total_estimated_tokens
├── context_window
└── usage_source ("estimated" | "actual")
```

写入位置：
- Session events: `.pico/sessions/<id>.events.jsonl`
- Run trace: `.pico/runs/<run-id>/trace.jsonl`
- Run report: `.pico/runs/<run-id>/report.json`

---

## 10. 测试策略

### 10.1 测试分层

```
                    ┌──────────────────────┐
                    │   Acceptance Tests   │  2 files, 6 tests
                    │  (真实 runtime 流程)  │  ScriptedModelClient + 真实文件系统
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Integration Tests   │  3 files, 35 tests
                    │  (跨模块交互验证)     │  Cost experiment, CLI commands, events
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │    Unit Tests        │  9 files, 41 tests
                    │  (单模块行为验证)     │  Mocks, fixtures, 隔离
                    └──────────────────────┘
```

**总计：14 个测试文件，82 个测试，测试代码与源码比约 1:1。**

### 10.2 各模块测试覆盖

| 测试文件 | 测试数 | 类型 | 验证什么 |
|----------|--------|------|----------|
| `test_compact.py` | 8 | 单元 | plan 确定性、LLM/deterministic 分支、增量 compact、no-op 检测 |
| `test_context_manager.py` | 8 | 单元 | Section 组装顺序、预算裁剪、relevant memory 选择 |
| `test_context_pressure.py` | 8 | 单元 | 压力计算、identity 匹配/失配、cache token、URL 脱敏 |
| `test_context_handoff.py` | 10 | 单元 | 解析成功/失败、usage tracking、bad metadata 归零 |
| `test_context_replacements.py` | 8 | 单元 | 缓存命中、stale hash、changed path 作废 |
| `test_context_retention.py` | 4 | 单元 | Protected tool 保留、bulk tool 替换条件 |
| `test_context_sections.py` | 5 | 单元 | 注册表、裁剪顺序、floor 值 |
| `test_context_report.py` | 1 | 单元 | Report 结构符合 schema |
| `test_context_budget_summary.py` | 3 | 单元 | Usage 记录、净收益正/负、orchestrator 更新 |
| `test_context_orchestrator.py` | 7 | 单元 | 各触发路径、优先级、skip 条件 |
| `test_context_orchestrator_acceptance.py` | 2 | 集成 | 真实 turn → 事件链 → report |
| `test_context_governance_acceptance.py` | 4 | 集成 | 手动/自动 compact、事件写入、history 渲染 |
| `test_context_cost_experiment.py` | 13 | 集成 | 成本实验：paired rows、claimability、markdown report |
| `test_usage.py` | 11 | 集成 | CLI 命令输出、metadata 格式 |

### 10.3 测试基础设施

**ScriptedModelClient**（`pico/testing.py`）

```python
client = ScriptedModelClient(["response1", "response2", ...])
client.context_window = 1000
client.last_completion_metadata = {...}
# complete() 按顺序消耗 responses 列表
# 如果 responses[i] 是 Exception，该次调用 raise
```

用途：
- 模拟 LLM 输出（compact call + main turn 各消耗一个 response）
- 通过 `.prompts` 捕获所有发送给模型的 prompt
- 通过 `context_window` 控制压力比
- 通过 `last_completion_metadata` 模拟 provider 返回的 actual tokens

**架构边界守卫**（`test_architecture_boundaries.py`）

强制各模块行数上限，防止复杂度蔓延：

| 模块 | 上限 | 当前 |
|------|------|------|
| context_manager.py | 420 | 337 |
| context_handoff.py | 240 | 232 |
| context_orchestrator.py | 210 | 200 |
| context_replacements.py | 160 | 148 |
| context_pressure.py | 140 | 114 |
| context_sections.py | 140 | 106 |
| context_report.py | 140 | 101 |
| context_budget_summary.py | 130 | 120 |
| context_usage.py | 120 | 110 |
| context_retention.py | 90 | 69 |

**信号：** 如果你需要在某个模块里加超过 10 行逻辑就接近预算了，应该新建模块。

---

## 11. 验证方式

### 11.1 自动化验证（CI 层面）

```bash
uv run pytest -q tests/
# 82 tests → 全部绿色
```

覆盖所有单元和集成场景。每次 PR 必须全绿。

### 11.2 端到端 Runtime 验证（Phase 1 验证计划）

7 个场景模拟真实多轮 session，验证组件组合后的行为：

| 场景 | 验证目标 |
|------|----------|
| tier3 happy path | LLM handoff 在 runtime pipeline 中正确触发 |
| LLM 失败回退 | 解析失败时 deterministic 无缝接管 |
| 低压不触发 | tier0 下整个 compact 路径不被执行 |
| over-budget 优先 deterministic | 硬超限不浪费 LLM 调用 |
| delta 不足不触发 | < 4 events 时 compact call 被跳过 |
| ledger 不被破坏 | compact 不重置 replacement 缓存 |
| 净收益计算 | 正/负收益都正确记录 |

交付为：`scripts/validate_llm_handoff.py`（独立运行）+ `tests/test_llm_handoff_e2e.py`（纳入 CI）。

### 11.3 成本实验（量化验证）

`pico/evaluation/context_cost.py` 提供 paired experiment 框架：

- Treatment（full_orchestrator）vs Control（no_context_reduction）
- 同一 session history，两种模式各跑一次
- 对比：token count、cost、验证通过率
- 输出 markdown report + CSV

目的：证明上下文治理的**净效果**——不只是"主请求 prompt 变短了"，而是"算上所有副调用之后，总 token/cost 下降了"。

### 11.4 真实场景观察

手动运行 Pico 长 session（让 pressure 自然到 tier3）：

```bash
uv run pico --session-id test-handoff --model <your-model>
# 多轮对话后观察：
# /context → 查看 pressure_tier
# /usage → 查看 compact 事件
# 检查 .pico/sessions/test-handoff.events.jsonl
```

观察点：
- handoff summary 质量（是否保留了关键路径、变量名、错误信息）
- 净收益是正还是负
- compact 后主任务是否顺畅继续

---

## 12. 关键不变式

无论系统如何演化，以下条件必须始终成立：

1. **compact 永远不中断主任务。** LLM compact 的任何失败都必须有 deterministic fallback。
2. **低压路径无漂移。** tier0/tier1 的 prompt 输出必须和没有上下文治理时完全一致。
3. **compact_call_usage 不持久化。** 它是 transient metadata，不写入 session 文件。
4. **replacement ledger 不被 compact 修改。** compact 只改 history + context_summary。
5. **Section 裁剪有 floor。** current_request 永不裁剪，其他 section 不低于 floor。
6. **cost 计算是诚实的。** 负收益不被隐藏。
7. **架构预算被测试守卫。** 超限直接 test failure。

---

## 13. Phase 路线

| Phase | 状态 | 内容 |
|-------|------|------|
| Phase 0: Deterministic 治理 | ✅ 完成 | Budget/sections/retention/replacement/pressure/report |
| Phase 1: LLM Handoff Compact | ✅ 代码完成，待验证 | HandoffAdapter, tier3 trigger, fallback, net benefit |
| Phase 2: UI + 完整观测 | 待启动 | `/compact --llm`, final readiness reason, retention taxonomy |
| Phase 3: 大规模实验 | 待启动 | Live provider benchmark, encrypted blob, 多模型对比 |

---

## 14. 文档索引

| 文档 | 用途 |
|------|------|
| `docs/superpowers/plans/2026-06-19-context-orchestrator.md` | Orchestrator 原始设计 |
| `docs/superpowers/plans/2026-06-19-context-cost-experiment.md` | 成本实验框架设计 |
| `docs/superpowers/reviews/2026-06-20-context-convergence.md` | Orchestrator 收敛 review |
| `docs/superpowers/plans/2026-06-21-llm-handoff-context-compaction.md` | LLM Handoff 完整 north-star |
| `docs/superpowers/plans/2026-06-22-llm-handoff-context-compaction-scope-note.md` | Phase 1 范围收敛 |
| `docs/superpowers/plans/2026-06-22-llm-handoff-compaction-impl-plan.md` | Phase 1 实施计划（给 Codex） |
| `docs/superpowers/reviews/2026-06-22-llm-handoff-compaction-impl-review-brief.md` | Phase 1 code review brief |
| `docs/superpowers/plans/2026-06-22-llm-handoff-phase1-validation-plan.md` | Phase 1 端到端验证计划 |
