# Pico Resume Benchmark Summary

Date: 2026-05-23

Branch: `codex/picobench-v3`

Commit: `2372068723af8b1c06b3e43362193e91fdbe3c41`

This document records the benchmark evidence that is safe to compress into a
resume project description. It separates deterministic harness regression,
module ablations, live provider runs, and resume wording so the resume does not
mix model quality, system capability, and audit evidence into one vague score.

## Fresh Verification

| Layer | Command / artifact | Result |
|---|---|---|
| Unit and integration tests | `uv run pytest tests/ -q` | `267 passed, 2 skipped, 6 warnings` |
| Core task quality | `/tmp/picobench-20260523-quality.json` | 30 tasks, 30 hidden fixtures, no issues |
| L0 runtime regression | `/tmp/picobench-20260523-runtime/runtime_artifact.json` | 2/2 passed, verifier pass rate 100% |
| Harness regression v2 | `/tmp/pico-20260523-resume-metrics-full/artifacts/harness-regression-v2.json` | 12/12 passed, within-budget 100%, verifier 100% |
| Context ablation v2 | `/tmp/pico-20260523-resume-metrics-full/artifacts/context-ablation-v2.json` | 12 configs, current request preserved 100% |
| Working-memory ablation v2 | `/tmp/pico-20260523-resume-metrics-full/artifacts/memory-ablation-v2.json` | repeated reads 60 -> 0 |
| Recovery ablation v2 | `/tmp/pico-20260523-resume-metrics-full/artifacts/recovery-ablation-v2.json` | workspace drift detection 100%, false accept 0% |
| Core full live run | `/tmp/picobench-20260523-core30/summary.json` | 30 tasks, 22 strict passes, 8 strict failures |
| Agentic-native live run | `/tmp/picobench-20260523-agentic-native/summary.json` | 3 tasks, 2 strict passes, 1 evidence failure |
| v3 human-gate agentic live run | `/tmp/picobench-20260523-agentic-v1/summary.json` | 12/12 strict passes |
| Ablation runner | `/tmp/picobench-20260523-ablation/ablation_summary.json` | 5 planned variants; live ablation still blocked by missing public feature flags |

## Resume-Safe Numbers

- Model backend surface: 3 backend/protocol families in v3 documentation and code
  paths: Ollama, OpenAI-compatible Responses, and Anthropic-compatible Messages.
- Tool surface: 7 tool families in the runtime/evaluation resume metrics.
- Run artifact surface: 3 durable execution artifact classes used in the resume
  metrics: report, trace, and task/session state evidence.
- Harness regression: 12 fixed deterministic tasks, 100% pass rate, 100%
  budget-within rate, 100% verifier pass rate.
- Context governance: 12 long-context configurations. Average prompt size went
  from 13327.67 raw chars to 12069.00 rendered chars, average compression
  8.29%, max compression 17.77%, current request preserved 100%.
- Working memory: across 12 memory-dependent tasks with 5 repetitions each,
  follow-up repeated file reads went from 60 to 0.
- Recovery: 10 recovery scenarios; resume-enabled success rate 90%, stale
  re-anchor rate 100%, workspace drift detection 100%, false accept rate 0%.
- Live DeepSeek core run: 30 core tasks, 22 strict passes, 8 strict failures,
  strict pass rate 73.33%, evidence consistency 100%, timeout count 0.
- Live DeepSeek agentic gate: 12 v3 human-gate scenarios, 12/12 strict passes.

## Live Failure Taxonomy

The 2026-05-23 full core live run is useful because it did not produce a fake
green score. It exposed real model/process limits while keeping the runner and
evidence path consistent.

| Task | Category | Signal |
|---|---|---|
| `core_016` | `hidden_test_failure` | numeric strings were not accepted by the JSON filter |
| `core_018` | `hidden_test_failure` | todo parser did not trim extra spaces |
| `core_019` | `hidden_test_failure` | URL join kept a trailing slash on empty path |
| `core_023` | `hidden_test_failure` | Markdown table rendered `None` instead of empty cell |
| `core_027` | `hidden_test_failure` | no-frontmatter and empty-tag markdown edges failed |
| `core_028` | `hidden_test_failure` | blank token was over-redacted in permission audit |
| `core_029` | `tool_policy_violation` | patch wrote `config.py` before reading that exact path |
| `core_030` | `hidden_test_failure` | scheduler treated implicit dependency nodes as a cycle |

## Resume Wording

Pico：本地代码智能体 Harness

核心技术：Python、Agent Harness、Tool Calling、Context Management、
Checkpoint / Resume、Layered Memory、Run Trace、Benchmark / Verifier

项目描述：
面向代码仓库长链路任务开发本地代码 agent harness，围绕模型接入、工具调用、
上下文管理、任务恢复、结构化记忆、运行审计和评测闭环做系统化设计，重点解决
多轮代码任务里的 prompt 膨胀、重复读文件、状态丢失、工具副作用不可控和结果
难复盘的问题。

核心职责与贡献：

1. Agent Harness 架构设计：负责本地代码 agent 的整体设计与开发，统一模型接入、
   工具执行、会话状态、checkpoint 恢复和运行工件落盘流程，形成可复盘的执行链路；
   支持 3 类模型后端、7 类工具族和 3 类运行工件。
2. 长上下文治理：设计分层上下文管理与预算裁剪机制，在 12 组长上下文配置里，
   将平均 prompt 长度从 13327.67 字符压到 12069.00 字符，平均压缩率 8.29%，
   最高压缩率 17.77%，同时保持当前请求 100% 不被裁掉。
3. 结构化记忆系统：针对多轮任务里 agent 反复读同一文件、重复确认已知事实的问题，
   将任务摘要、文件摘要、过程笔记和相关记忆召回做分层；在 12 个记忆依赖任务、
   5 轮重复实验里，follow-up 阶段重复读文件次数从 60 次降到 0 次。
4. 任务恢复机制：设计 checkpoint / resume 机制，让 agent 在上下文超预算、
   中断恢复和 workspace 漂移场景下恢复任务状态，而不是重读整段聊天历史；覆盖
   10 个恢复场景，workspace 漂移识别率 100%，误信旧状态继续执行的比例为 0%。
5. 工具安全与运行治理：构建标准化工具调用与安全边界，覆盖参数校验、工作区隔离、
   高风险审批、重复调用拦截、敏感信息脱敏和部分成功情况识别；固定 harness
   regression 中 12/12 通过，预算内完成率 100%，verifier 通过率 100%。
6. 评测与审计闭环：将评测拆成 harness regression、上下文治理、记忆收益、
   恢复正确性、core live run 和 agentic gate 几层，分别验证运行时合同稳定性、
   模块收益、模型补丁质量和恢复边界；当前 DeepSeek full core live run 为
   30 题 22 个 strict pass，v3 human-gate agentic 场景为 12/12 strict pass，
   并通过 failure taxonomy 区分 hidden-edge 失败、工具流程违规和证据一致性问题。
