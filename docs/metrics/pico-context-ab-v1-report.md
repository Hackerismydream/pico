# Pico Context A/B V1 Report

## 目标

验证 Pico V1 上下文治理链路在不引入额外 LLM compact 调用的前提下，是否能降低模型调用前的输入 token，同时不造成质量回退。

本报告对应的治理链路包括：

- 上下文预算管理
- 压力感知裁剪
- 分层信息保留
- 结构化 compact 摘要
- typed token 估算
- trace 观测
- 成对 A/B 成本评测

## 实验设计

实验采用 paired A/B，对同一个任务和同一个 repeat 同时跑两种变体：

- `no_context_reduction`：关闭上下文治理，作为 baseline。
- `full_orchestrator`：开启当前 V1 上下文治理链路。

当前 deterministic 模式只构造 prompt，不调用真实 provider。token 来自 Pico 的 typed token estimator，所以结果口径是 estimated input tokens，不是 provider billing tokens。

净收益公式：

```text
net_saved = baseline_input_tokens - optimized_input_tokens - compact_call_tokens
```

V1 当前使用 deterministic compact，没有额外 LLM 调用，因此：

```text
compact_call_tokens = 0
```

后续如果接入 LLM handoff compact，必须把 compact 自身消耗的 input/output tokens 从收益里扣掉。

## 复现命令

从 repo 根目录执行：

```bash
python3 -m pico.evaluation.context_cost --mode deterministic --output-dir artifacts/context-ab-v1
```

产物：

- `artifacts/context-ab-v1/results.json`
- `artifacts/context-ab-v1/report.md`
- `artifacts/context-ab-v1/paired_rows.csv`

验证回归：

```bash
python3 -m pytest tests/ -x -q
```

敏感信息检查：

```bash
grep -RInE 'sk-|api_key|api-key' artifacts/context-ab-v1
```

无输出代表产物中未发现常见密钥标记。

## 当前结果

采集时间：2026-06-24

| 指标 | 结果 |
| --- | ---: |
| paired_task_count | 1 |
| baseline estimated input tokens / task | 5547 |
| optimized estimated input tokens / task | 4023 |
| net saved estimated input tokens / task | 1524 |
| median_cost_delta_pct | -27.47% |
| claimable_cost_win | True |
| quality_regression_count | 0 |

解释：

- baseline 是 `no_context_reduction`。
- optimized 是 `full_orchestrator`。
- `claimable_cost_win=True` 表示该 paired bucket 同时满足成本下降、验证通过、无质量回退、无负向 compact net benefit。
- `quality_regression_count=0` 表示当前 deterministic A/B 没有观察到质量回退。
- 早期 M5 工作区 snapshot 是 5765 -> 4241，净省同样为 1524 tokens；合入当前 v3 clean worktree 后，workspace prompt surface 略有变化，所以绝对 token 数更新为 5547 -> 4023。

## 回归结果

最终回归命令：

```bash
python3 -m pytest tests/ -x -q
```

结果：

```text
407 passed, 2 skipped, 12 warnings
```

## 结论边界

可以声明：

- 在 deterministic context A/B 中，估算输入 token 从 5547 降到 4023，下降 27.47%。
- 当前 paired run 未观察到质量回退。
- 当前实现具备可复现的成本评测产物和净收益报告。

不能声明：

- 不能把本结果直接写成真实 provider 账单下降。
- 不能把 deterministic estimated tokens 等同于 live provider actual input tokens。
- 不能把单个 deterministic paired task 扩大成所有代码任务的平均收益。

下一步如果要声明真实成本收益，需要运行 live provider A/B，并且只使用 `usage_source=actual` 的 paired rows 作为正式口径。
