# Pico v4 优化说明

这次升级围绕五个模块做，不扩成大而全平台。目标是让 Pico 从一个能跑的本地 coding agent，变成一个能经得住二三面追问的 runtime/harness 项目。

## 参考来源和取舍

| 模块 | 主要参考 | Pico v4 的取舍 |
| --- | --- | --- |
| Context | `cc-mini` 的 compact 保留策略，Claude Code 的 context usage 思路 | 补 token 估算、section breakdown、首轮 prompt 去重和手动 `/compact`，compact 先做本地可解释摘要 |
| Trace / Session | `pi-mono/packages/coding-agent` 的 JSONL session entry，Claude Code 的多阶段 query loop | 先双写 session events 和 trace-v2，不破坏旧 session JSON |
| Tool Policy | Claude Code 的 permission pipeline，`cc-mini` 的 plan mode，`pi` 的工具 guideline 和长输出保存 | 落 allowed_tools、prior read ledger、tool protocol、plan mode 和 tool artifact，不急着做完整 hook DSL |
| Skill | Claude Code 的 skill discovery/prefetch | 先做本地 `SKILL.md` 命中和 prompt 注入，保持简单可解释 |
| SDK | Anthropic 官方 SDK，right.codes 的 OpenAI/Claude 双 endpoint | SDK 做可选 transport，不替换 OpenAI-compatible 和 Anthropic-compatible HTTP client |

这条路线的核心判断是：面试官真正关心的不是 Pico 有没有复制 Claude Code，而是你能不能讲清楚一个 agent runtime 的控制面。五个模块分别对应控制面的五个问题：上下文怎么治理，过程怎么审计，工具怎么约束，能力怎么扩展，模型怎么接入。

## Context 升级解决什么问题

原来的 Pico 已经有 `ContextManager`，但它主要是 char budget。二面被问到用户只输入 `hi` 时 prompt 长什么样、占多少 token，只能解释大概，不能给稳定字段。

v4 做了四件事：

- 新增 `pico/features/context_usage.py`，把 prompt 和每个 section 的 rendered chars 估算成 token，并记录模型窗口和输出预留。
- 把 `skills` 放入上下文顺序，但只有命中技能才渲染，避免空技能段浪费上下文。
- 调整 `ask()` 的记录顺序，首轮 prompt 构建完成后才把当前 user message 写入 history，避免当前请求在 `Transcript` 和 `Current user request` 里重复出现。
- 增加 `compact_history()` 和 `/compact [n]`，把旧 history 压成一条 `[compacted context]` 摘要，并把压缩事件写入 session events。

面试回答可以这样讲：Pico 的 context pack 不是把历史一股脑塞进去，而是分成稳定 prefix、工作记忆、技能、相关记忆、历史和当前请求。当前请求最后放且不裁剪；旧历史可以通过 `/compact` 压成可恢复摘要；每轮 report 都能看到估算 token 和剩余窗口。

## Trace / Session 升级解决什么问题

原来的 `trace.jsonl` 能看过程，但 schema 更像日志。session JSON 能恢复，但不适合表示一次 turn 里的 user、tool、assistant、checkpoint 事件。

v4 做了双写：

- 旧 session JSON 继续保存可恢复状态。
- 新增 `<session_id>.events.jsonl`，按事件追加 user message、assistant message、tool result、skill_selected 等。
- trace 事件升级为 `trace-v2`，增加 `trace_id`、`span_id`、`turn_id`、`phase`、`status`、`sequence`。
- `report.json` 记录 trace path 和 session events path，复盘时能从报告跳回原始证据。

这样回答 run trace 的问题更稳：Pico 自研 trace 不是为了替代 Datadog 这类 APM，而是因为本地 coding agent 需要把 prompt metadata、工具参数、workspace diff、checkpoint、session turn 绑定在同一个离线工件里。外部 tracing 可以作为 exporter，不能反过来决定本地 schema。

## Tool Policy 升级解决什么问题

原来的工具层有白名单、schema 校验、risky approval、read_only 和 shell safety，但工具策略还是散落在代码里。v4 把工具协议和运行模式显式化。

每个工具现在有 protocol：

- schema
- description
- risky
- read_only
- activity

每个工具也有 policy：

- read-only 还是 mutating
- 能不能并发
- 是否要求 prior read
- 长结果最多放多少进 prompt

`patch_file` 要求先 `read_file`，并记录文件 freshness。这个设计能回答文件修改为什么安全：模型不能凭空 patch 一个没看过的文件，也不能读完以后在文件变了的情况下继续用旧上下文 patch。

benchmark 里的 `allowed_tools` 也不再只是数据字段。`BenchmarkEvaluator` 会把任务允许的工具传进 runtime，CLI 也新增 `--allowed-tool`。这能支撑工具目录扩展后的设计：即便未来有 5000 个工具，runtime 也应该先经过 tool retrieval / allowed set，再暴露给模型，而不是把全量 schema 都塞进 prompt。

Plan mode 是这一层的新状态。`/plan [topic]` 创建 `.pico/plans/<id>.md`，prefix 会声明当前处于 plan mode；运行时只允许读工具和写当前 plan 文件。`/execute` 退出 plan mode。这样 Pico 能把探索、写计划、真正改代码分成两个可审计阶段。

## Skill 升级解决什么问题

Skill 的作用不是让 Pico 看起来像有插件系统，而是解决 prompt 注入的边界问题。过去如果想让 agent 按某个项目规则工作，只能把规则写进 prefix 或用户请求；prefix 会越来越大，用户请求又不稳定。

v4 增加 `pico/features/skills.py`：

- 扫描 `.pico/skills/*/SKILL.md` 和 `skills/*/SKILL.md`
- 解析 `name` 和 `triggers`
- 用户消息命中后才注入 `Active skills`
- 选中结果进入 metadata 和 session events

这个设计的面试口径是：Skill 是局部能力包，不是长期记忆。长期记忆记录稳定事实，skill 记录某类任务的操作协议。两者都进 prompt，但生命周期不同。

## SDK 升级解决什么问题

原来的 provider 层已经支持 Ollama、OpenAI-compatible、Anthropic-compatible 和 DeepSeek。v4 增加 Anthropic SDK 不是为了炫 SDK，而是为了把 provider capability 讲清楚。实现参考 Anthropic 官方 [API overview](https://docs.anthropic.com/en/api/overview) 和 [Client SDKs](https://docs.anthropic.com/en/api/client-sdks) 文档：SDK client 负责认证细节，业务代码通过 `messages.create` 发起 Messages API 调用。

当前模型接入分三层：

- runtime 只依赖 `complete()` 抽象
- HTTP-compatible client 负责兼容网关和自部署服务
- SDK client 负责使用官方 SDK 的消息 API 和后续 provider 特性

`--provider anthropic-sdk` 会走 `AnthropicSDKModelClient`。依赖放在 optional extra 里：

```toml
[project.optional-dependencies]
anthropic = ["anthropic"]
```

right.codes 的合理使用方式是：codex endpoint 继续走 OpenAI-compatible；Claude endpoint 可以走 Anthropic-compatible HTTP，也可以走 Anthropic SDK transport。SDK 不应该成为唯一入口，否则本地模型、自部署网关和 OpenAI-compatible provider 都会被排除掉。

## 这次升级后的简历表述

可以把 Pico 从文档工具改成 runtime/harness 项目来写：

> 实现一个本地 coding agent harness，包含上下文装箱与 token 预算观测、手动 compact、turn-aware session event、span-like run trace、工具 protocol/policy 闸口、plan/execute 运行模式、技能注入和多 provider SDK/HTTP 接入。工具执行支持 allowed tools、patch 前置 read/freshness 校验、长输出 artifact 落盘；每次运行生成 task_state、trace、report 和 session events，支持 benchmark 复盘和 resume 诊断。

这段比简单写 prompt engineering 或接模型更抗问，因为它背后每个词都能落到代码文件：

- context：`pico/features/context_manager.py`、`pico/features/context_usage.py`
- session/trace：`pico/core/agent.py`、`pico/core/run_store.py`
- tool policy：`pico/tools/registry.py`、`pico/tools/shell_safety.py`
- skill：`pico/features/skills.py`
- sdk：`pico/providers/clients.py`、`pico/cli.py`

## 后续最值得继续做的三件事

**Semantic compact**，当前 `/compact` 是本地可解释摘要。下一步可以把摘要器升级成模型生成，但输出结构仍然固定为 Goal、Files read、Files modified、Key decisions、Next step，并继续写入 trace 和 checkpoint。这个方向最能回应上下文过长问题。

**Session tree / model switch**，当前 events 是线性的。后续可以加 parent_event_id、branch_id、model_changed，让 session 支持 fork 和模型切换后的能力重算。这样能回答一个 session 里切模型会影响什么。

**Tool retrieval / permission pipeline**，当前 allowed_tools 是静态集合。后续可以加 tool catalog、query-time retrieval、deny/allow rule、hook callback，让工具扩展从 7 个工具自然过渡到大量工具，而不是把所有 schema 塞进 prompt。
