# PicoBench Handoff Archive 2026-05-24

This archive records the benchmark/resume-packaging work from the previous
turn, the user's original prompt, the assistant's final output, and the review
prompt to send to GPT Pro. It is intentionally repo-local so the claims can be
reviewed against the checked-out PicoBench code and artifacts.

## Repository State

- Workspace: `/Users/martinlos/code/pico`
- Branch: `codex/picobench-v3`
- Commit used for the fresh benchmark run:
  `2372068723af8b1c06b3e43362193e91fdbe3c41`
- Date of fresh run recorded by the assistant: 2026-05-23 Asia/Shanghai
- Archive date: 2026-05-24 Asia/Shanghai

## What Was Done

The assistant treated the user's goal as:

1. Finish the PicoBench benchmark development/run cycle on the current v3
   benchmark branch.
2. Rerun deterministic and live benchmark layers instead of using stale numbers.
3. Convert the benchmark evidence into a resume-facing project description.
4. Record the live run results and resume-safe metrics in repo docs.

The work performed in the previous turn:

- Rechecked the current branch and benchmark docs.
- Ran deterministic verification:
  - `uv run pytest tests/ -q`
  - `scripts/check_picobench_tasks.py`
  - `scripts/run_picobench_runtime.py`
- Ran resume-metric experiments:
  - harness regression v2
  - context ablation v2
  - working-memory ablation v2
  - recovery ablation v2
- Ran live DeepSeek benchmark suites:
  - full 30-task core suite
  - 3-task agentic-native suite
  - 12-task delegated v3 human-gate agentic suite
- Updated:
  - `docs/evaluation/live_execution_log.md`
  - `docs/evaluation/live_results_summary.md`
  - `docs/evaluation/phase3_plan.md`
- Added:
  - `docs/evaluation/resume_benchmark_summary.md`

## Fresh Results Recorded

| Layer | Result |
|---|---|
| Unit/integration tests | `267 passed, 2 skipped, 6 warnings` |
| Core task quality | 30 tasks, 30 hidden fixtures, no issues |
| L0 runtime regression | 2/2 passed |
| Harness regression v2 | 12/12 passed, within-budget 100%, verifier 100% |
| Context ablation v2 | 12 configs, `13327.67 -> 12069.00` chars, average compression 8.29%, max compression 17.77% |
| Working-memory ablation v2 | repeated reads `60 -> 0` |
| Recovery ablation v2 | workspace drift detection 100%, false accept 0% |
| DeepSeek core full live | 30 tasks, 22 strict passes, 8 strict failures, evidence consistency 100% |
| DeepSeek agentic-native | 3 tasks, 2 strict passes, 1 evidence failure |
| DeepSeek v3 human-gate agentic | 12/12 strict passes |

## Potential Misunderstanding To Review

The user later said: "我发现你好像理解错我意思了". The likely risk is that the
assistant optimized for "finish benchmark runs and produce resume wording" while
the user may have meant one of these stricter scopes:

- implement/fix the remaining benchmark gaps until all benchmark layers are
  truly strict-green;
- fix `agentic_native_memory_001` evidence bundling instead of only documenting
  its evidence failure;
- resolve or triage all 8 full-core live failures rather than preserving them as
  benchmark signal;
- produce a review-ready PR rather than only local docs and metrics;
- avoid presenting live model failures as "benchmark complete" if the user's
  completion standard meant "benchmark suite is complete and passing".

## Original User Prompt

```text
/goal 完成 整个benchmark的开发和运行，最后给出我类似，【Pico：本地代码智能体 Harness
核心技术：Python、Agent Harness、Tool Calling、Context Management、Checkpoint / Resume、Layered Memory、Run Trace
项目描述：
面向代码仓库长链路任务开发本地代码 agent harness，围绕模型接入、工具调用、上下文管理、任务恢复、结构化记忆、运行审计和评测闭环做系统化设计，重点解决多轮任务里 prompt 膨胀、重复读文件、状态丢失、工具副作用不可控和结果难复盘的问题。
核心职责与贡献：
1. Agent Harness 架构设计：负责本地代码 agent 的整体设计与开发，统一模型接入、工具执行、会话状态、checkpoint 恢复和运行工件落盘流程，形成可复盘的执行链路；支持 2 类模型后端、7 类工具和 3 类运行工件。
2. 长上下文治理：设计分层上下文管理与预算裁剪机制，在 12 组长上下文配置里，将平均 prompt 长度从 7082 压到 5664，平均压缩率 16.19%，最高压缩率 33.28%，同时保证当前请求不被裁坏。
3. 结构化记忆系统：针对多轮任务里 agent 反复读同一文件、重复确认已知事实的问题，把任务摘要、文件摘要、过程笔记和相关记忆召回做了分层；在 12 个记忆依赖任务里，follow-up 阶段的重复读文件次数从 60 次降到 0 次，且不再需要额外工具调用去重新确认已经拿到的事实。
4. 任务恢复机制：设计 checkpoint / resume 机制，让 agent 在上下文超预算、中断恢复和 workspace 漂移场景下恢复任务状态，而不是重读整段聊天历史；覆盖 10 个恢复场景，workspace 漂移识别率 100%，且没有出现误信旧状态继续执行的情况。
5. 工具安全与运行治理：构建标准化工具调用与安全边界，覆盖参数校验、工作区隔离、高风险审批、重复调用拦截、敏感信息脱敏和部分成功情况的识别；在固定回归任务中保持 100% 通过率、100% 预算内完成率和 100% verifier 通过率。
6. 评测与审计闭环：：将评测拆成 harness regression、上下文治理、记忆收益和恢复正确性几层，分别验证运行时合同稳定性、模块收益和恢复边界，避免把模型能力、系统能力和运行观测混成一个总分；形成固定 benchmark、对照实验和运行工件聚合三类评测路径。】这样的简历说明，基于v3和我们的benchmark
```

## Assistant Final Output From Previous Turn

```text
完成了。当前不是沿用旧指标，而是基于 `codex/picobench-v3` 当前 HEAD `2372068723af8b1c06b3e43362193e91fdbe3c41` 重新跑了一轮。

落盘文件：

- [resume_benchmark_summary.md](/Users/martinlos/code/pico/docs/evaluation/resume_benchmark_summary.md)
- [live_results_summary.md](/Users/martinlos/code/pico/docs/evaluation/live_results_summary.md)
- [live_execution_log.md](/Users/martinlos/code/pico/docs/evaluation/live_execution_log.md)
- [phase3_plan.md](/Users/martinlos/code/pico/docs/evaluation/phase3_plan.md)

关键结果：

- `uv run pytest tests/ -q`: `267 passed, 2 skipped`
- L0 runtime: `2/2`
- harness regression v2: `12/12`，预算内完成率 `100%`，verifier `100%`
- context ablation: 12 组配置，`13327.67 -> 12069.00` chars，平均压缩 `8.29%`，最高 `17.77%`
- memory ablation: repeated reads `60 -> 0`
- recovery ablation: workspace drift detection `100%`，false accept `0%`
- DeepSeek core full live: `30` 题，`22` strict pass，`8` strict failure，evidence consistency `100%`
- DeepSeek agentic-native: `3` 题，`2` strict pass，`1` evidence failure
- DeepSeek v3 human-gate agentic: `12/12` strict pass

简历口径已经写进 [resume_benchmark_summary.md](/Users/martinlos/code/pico/docs/evaluation/resume_benchmark_summary.md)。核心版本是：

> Pico：本地代码智能体 Harness
> 核心技术：Python、Agent Harness、Tool Calling、Context Management、Checkpoint / Resume、Layered Memory、Run Trace、Benchmark / Verifier
> 项目描述：面向代码仓库长链路任务开发本地代码 agent harness，围绕模型接入、工具调用、上下文管理、任务恢复、结构化记忆、运行审计和评测闭环做系统化设计，重点解决多轮代码任务里的 prompt 膨胀、重复读文件、状态丢失、工具副作用不可控和结果难复盘的问题。

注意：你给的示例里上下文压缩是 `7082 -> 5664 / 16.19%`，当前 fresh run 的真实数字是 `13327.67 -> 12069.00 / 8.29%`。我用了当前 benchmark 的实测值，没有沿用旧数字。

Goal 已标记完成。用量：`207830` tokens，用时约 `22m18s`。
```

## Prompt For GPT Pro Review

```text
你是 GPT Pro，请以资深工程 reviewer + benchmark 设计 reviewer 的角度审查这个 PicoBench 分支。

仓库路径：/Users/martinlos/code/pico
分支：codex/picobench-v3
重点文件：
- docs/evaluation/benchmark_handoff_archive_2026-05-24.md
- docs/evaluation/resume_benchmark_summary.md
- docs/evaluation/live_results_summary.md
- docs/evaluation/live_execution_log.md
- docs/evaluation/phase3_plan.md
- scripts/run_picobench.py
- scripts/run_picobench_runtime.py
- scripts/run_picobench_ablation.py
- pico/evaluation/cli_runner.py
- pico/evaluation/report_card.py
- pico/evaluation/validators.py
- benchmarks/picobench-core-v1.yaml
- benchmarks/picobench-agentic-native-v0.yaml
- benchmarks/picobench-agentic-v1.yaml

用户原始目标是：完成整个 benchmark 的开发和运行，最后基于 v3 和 benchmark 产出一段可以写进简历的 Pico 项目描述。用户现在怀疑 Codex 理解错了意思。

请重点 review：
1. “完成整个 benchmark 的开发和运行”到底有没有被满足？如果没有，缺口是什么？
2. Codex 把 30-task core live run 的 8 个 strict failures 当作 benchmark signal 留档，而不是继续修到全绿，这是否违背用户目标？
3. `agentic_native_memory_001` functional pass 但 strict 失败在 evidence bundle，这应该被视作 benchmark 未完成、runner bug、任务设计问题，还是可接受留档？
4. `scripts/run_picobench_ablation.py` 仍然是 plan-only，是否说明“整个 benchmark”还没有完成？如果要完成，需要补哪些 feature flags 或实验控制？
5. `docs/evaluation/resume_benchmark_summary.md` 里的简历指标是否都能从 artifacts / code 里追溯？有没有夸大、混淆 deterministic harness、live model benchmark、module ablation 的地方？
6. 简历文案是否应该写 3 类模型后端，还是用户原始模板里的 2 类模型后端？请根据当前代码和 docs 判断。
7. 请列出必须修复的问题、建议修复的问题、以及可以保留为 benchmark signal 的失败项。
8. 最后给一个更准确的“完成定义”：如果让你接手，要做到哪一步才可以说这个 benchmark 工作真正完成？

请不要只做文字评价。请先读代码和文档，再给出带文件路径和证据的 review。输出用中文，结论先行。
```
