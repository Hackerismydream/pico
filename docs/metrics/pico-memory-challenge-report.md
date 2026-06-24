# Pico Memory Challenge Benchmark

## 简历口径

设计并实现 Pico 面向 Coding Agent 的长期记忆系统，支持结构化检索、事实更新与遗忘、过期证据拒用、敏感信息隔离、跨会话推理和任务恢复；构建 55 题无模型依赖记忆挑战基准，对比无记忆、朴素最近记忆、不安全记忆三类基线，将回答准确率从 41.82% 提升至 94.55%，证据召回率提升至 100%，并将敏感信息泄露、过期记忆误用、错误恢复接受率降至 0%。

## 做了什么

这个 benchmark 不接 live provider，不依赖 LLM 输出，也不引入 vector DB 或 embedding store。它把 Pico 的长期记忆能力拆成两个层次：

- Contract verification：8 个机制合同 case，验证结构化检索、supersede、quarantine、stale evidence、abstention 和跨 session 组合证据没有坏。
- Challenge benchmark：55 个 coding-agent 场景 case，覆盖信息抽取、跨会话推理、事实更新、时间/过期证据、无证据拒答、执行效率和恢复安全。

Challenge benchmark 使用同一组 case 跑四种 variant：

- `memory_on`：使用 Pico 的结构化 memory retrieval，过滤 superseded、quarantined、stale 和 scope mismatch 记忆。
- `memory_off`：不使用长期记忆，只能拒答或重新读取上下文，用来衡量记忆带来的召回和效率收益。
- `naive_recent`：按最近记忆做朴素选择，不理解 supersede、secret、stale 和 scope mismatch，用来模拟常见的简单 memory buffer。
- `unsafe_memory`：使用记忆但不执行安全过滤，用来验证敏感信息、过期证据和错误恢复是否会进入答案路径。

## 指标含义

- `answer_accuracy`：最终答案是否等于 case 的期望答案。
- `case_pass_rate`：答案正确，并且 required evidence 被选中、forbidden memory 未被选中。
- `evidence_recall_at_k`：应召回证据中有多少被选中。
- `evidence_precision_at_k`：选中记忆中有多少是 required evidence。
- `stale_use_rate`：过期证据 case 中，过期记忆被用于答案的比例。
- `secret_exposure_rate`：敏感信息 case 中，secret-shaped memory 被泄露到答案路径的比例。
- `false_resume_accept_rate`：无效恢复 case 中，错误 checkpoint 或跨 workspace 记忆被接受的比例。
- `avg_repeated_reads`：follow-up 任务里因为没有可用记忆而需要重复读取上下文的平均次数。

## 当前结果

| Variant | Answer accuracy | Evidence recall@k | Evidence precision@k | Stale use | Secret exposure | False resume accept | Repeated reads/task |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `memory_on` | 94.55% | 100.00% | 87.23% | 0.00% | 0.00% | 0.00% | 0.00 |
| `memory_off` | 41.82% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.58 |
| `naive_recent` | 38.18% | 92.68% | 52.05% | 100.00% | 100.00% | 100.00% | 0.00 |
| `unsafe_memory` | 38.18% | 92.68% | 52.05% | 100.00% | 100.00% | 100.00% | 0.00 |

Case 分布：

- `information_extraction`：9
- `multi_session_reasoning`：9
- `knowledge_updates`：9
- `temporal_reasoning`：11
- `abstention`：8
- `agentic_efficiency`：9

`memory_on` 当前保留 3 个失败 case，均是有意暴露的 schema 边界：当两条 active 记忆互相冲突但没有 `supersedes`、validity 或 scope metadata 时，系统会召回冲突证据，而不是主动拒答。这些失败不能写成系统能力成功，只能写成后续改进方向。

## 如何复现

在 repo 根目录运行：

```bash
uv run python -m pico.evaluation.metrics --run memory_challenge
uv run python -m pico.evaluation.metrics --run memory_agent_eval
uv run python -m pico.evaluation.metrics --core-report
uv run pytest tests/test_memory_agent_eval.py tests/test_metrics.py -q
uv run pytest tests -q
```

生成文件：

- `_local/benchmark/artifacts/memory-challenge-v1.json`
- `_local/benchmark/artifacts/memory-agent-eval-v1.json`
- `docs/metrics/pico-memory-evaluation-report.md`
- `docs/metrics/pico-benchmark-core-report.md`

其中 `_local/benchmark/artifacts/*.json` 和 `docs/metrics/pico-memory-evaluation-report.md` 是本地生成物，不作为源代码提交；`docs/metrics/pico-memory-challenge-report.md` 固化复现口径和当前指标，`docs/metrics/pico-benchmark-core-report.md` 保留 core report 的摘要视图。

## 保护边界

这组改动没有改变以下既有 artifact 字节内容：

- `_local/benchmark/artifacts/memory-ablation-v2.json`
- `_local/benchmark/artifacts/context-ablation-v2.json`
- `_local/benchmark/artifacts/recovery-ablation-v2.json`
- `_local/benchmark/artifacts/harness-regression-v2.json`

这组改动也没有引入 vector DB、embedding store、live provider，且没有重构 `LayeredMemory` 或 `DurableMemoryStore` 的主存储后端。
