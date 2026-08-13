# P11｜PicoBench：一次 Agent 实验怎样变成可核对的证据

> P07 里有一项很诱人的改动：减少模型每轮看到的工具定义。P11 跟着这项改动走完一次实验，看任务怎样冻结、两组方案怎样配对、失败怎样保留，以及一个省了很多 token 的方案为什么仍被挡在正向结论之外。

## 读前准备

这一章会用到三个日常概念：

- **对照组**：保留当前做法，用来回答“原来表现怎样”；
- **实验组**：只改变一个准备验证的因素；
- **Verifier**：按冻结规则检查任务结果，不让模型用自己的最终回复给自己判分。

本章对应 `origin/main@9914182c7bafa3d3e2a7a5564e792fc9d6d524b7`。实验计划、失败分类、工件保存、报告重建和结论门槛均以这份 `main` 源码为准。文中性能数字来自各自冻结的实验工件，只适用于报告写明的任务、模型、预算和 Verifier。

## 读完本章，你能回答什么

- 一项 Agent 改动怎样从冻结计划走到可重建报告？
- 为什么失败、超时和重试都要进入原始证据？
- 为什么工具定义 token 下降 `93.4513%`，方案仍没有通过正向 Gate？

## 先看这次要验证的改动

Pico 的完整工具目录很大。每轮模型调用都发送全部工具定义，会占用输入窗口。一个候选方案采用渐进式 Tool Disclosure：模型起初只看到搜索和调用入口，需要某个具体工具时再查询。

实验跑完后，报告最醒目的两行是：

```text
模型可见 Schema 估算 token：下降 93.4513%
任务通过数：control 23/24，treatment 20/24
```

输入明显变短，任务通过数却少了 3 个。PicoBench 要保存这两项结果，并阻止第一项单独进入正向结论。

要验证这个方案，不能只比较两次请求的 token 数。至少要固定这些条件：

```text
同一批任务
同一个 Provider 和模型
同一份底层工具目录
同样的超时和调用预算
同一个任务 Verifier
唯一变化：模型起初能看到哪些工具定义
```

最后一行是 treatment axis，也就是本次实验唯一允许变化的轴。只要两组还在其他设置上不同，就无法把结果归因给 Tool Disclosure。

## 先认代码：一份证据的七站

| 阶段 | 主要文件与符号 | 这一站做什么 |
|-|-|-|
| 1. 写实验 | `benchmarks/picobench/schema.py::ExperimentSpec`、`benchmarks/picobench/packs/tool_mcp/pack.py::ToolMCPPack.definition` | 冻结整场配置，再由任务包声明任务、组别和配对 |
| 2. 编计划 | `benchmarks/picobench/plan.py::compile_plan` | 展开所有 Trial、Pair 和 Comparison Block，计算实验身份 |
| 3. 跑任务 | `benchmarks/picobench/harness.py::run` | 按计划执行两臂，处理对称重试与恢复 |
| 4. 走真实运行时 | `benchmarks/picobench/host.py::RuntimeTrialHost.run` | 经 Scheduler、Agent Loop 和 Delivery 执行，再做外部验收 |
| 5. 保存原始记录 | `benchmarks/picobench/artifacts.py::ArtifactStore` | 保存 manifest、attempt、trial、pair 和 journal |
| 6. 重新计算 | `benchmarks/picobench/reducer.py::reduce_experiment` | 检查分母、配对和证据完整性，计算指标 |
| 7. 出报告 | `benchmarks/picobench/report.py::rebuild_full_report` | 写报告、digest 和受 Gate 约束的指标出口 |

第一遍沿着这七站读即可。Pack 就是一类任务及其对照关系；每个 Pack 的具体运行器、成本守卫和统计细节可以留到第二遍。

## 第 1 站：先把实验问题写死

入口是 `ExperimentSpec`。它保存 suite、重复次数、启用哪些 Pack、输出目录、环境身份、执行策略和 Claim Rule。具体任务、实验臂与配对关系由 `PackDefinition` 提供；Tool/MCP 这一类由 `ToolMCPPack.definition()` 构造。

第一次看这些类型，只读少量字段：

```python
TaskSpec(task_id="tool-formal-01", payload={...})

VariantSpec(
    variant_id="tool-mcp-all-tools",
    settings={"tool_disclosure": "all_tools"},
)

PairSpec(
    treatment_axis="tool_disclosure",
    control_variant_id="tool-mcp-all-tools",
    treatment_variant_id="tool-mcp-progressive",
)
```

`TaskSpec` 说明跑什么任务，`VariantSpec` 说明这一臂采用什么设置，`PairSpec` 指定两臂和唯一变化轴。这里先不用展开 payload，只要能指出任务、组别和变化轴即可。

执行策略还会冻结单 Trial 超时、Provider 调用上限、Comparison Block 尝试次数和每个 Pack 的 token 预算。看到结果后再增加某一臂的重试次数，会改变实验条件，因此必须创建新的实验身份。

## 第 2 站：compile_plan 展开完整分母

`compile_plan()` 把抽象配置展开成一份明确计划。假设 Tool/MCP Pack 有 8 个任务、2 个 Variant、3 次重复，计划会得到：

```text
8 tasks × 2 variants × 3 repetitions = 48 Trials
8 tasks × 3 repetitions = 24 Comparison Blocks
每个 Block 同时拥有 control 和 treatment
```

计划里还保存 Pair、检索用例和 Pack 定义。规范化后的计划会计算 `plan_digest`，实验目录也由计划身份确定。

`ArtifactStore.freeze_manifest()` 第一次运行时写入 manifest。目录已经有 manifest 时，新计划必须得到完全相同的规范字节，否则拒绝续跑。这样可以避免把另一批任务、另一个模型或另一组 Claim Rule 追加到旧结果中。

## 第 3 站：两臂在同一个 Block 里运行

PicoBench 以 Comparison Block 为重试单位。同一个任务、同一次重复的 control 和 treatment 属于一个 Block。

计划会先按规范化 digest 固定两臂的运行顺序，所以 control 不一定排在第一位。正常路径是：

```text
读取 Block
→ 按计划中的冻结顺序运行第一臂
→ 按同一顺序运行第二臂
→ 两臂都形成可测量结果
→ 选择同一个 block_attempt
→ 写 Trial 与 Pair 摘要
```

可测量的任务结果包括 `passed`、`task_failed` 和 `task_timeout`。这些状态表示运行条件有效，Verifier 可以对任务表现作出判断。

Provider 或基础设施失败时，本次 attempt 仍会保存。预算允许重试时，下一次会重跑整个 Block，control 和 treatment 都得到新的同号 attempt。报告不会拿 control 的第一次结果去配 treatment 的第二次结果。

## 第 4 站：Trial 经过真实 Runtime 和外部 Verifier

Agent 类任务由 `RuntimeTrialHost` 组装真实 Runtime。一次 `run()` 会提交 `TurnRequest`，等待 `TurnHandle`，再等待 Delivery 队列排空。最终记录同时保留：

- Runtime 怎样结束；
- 消息是否送到 Outlet；
- Provider 失败属于哪一类；
- Verifier 是否通过。

于是会出现这种有效记录：

```text
runtime_state = completed
delivery_state = delivered
verification = failed
trial_status = task_failed
```

Agent 完成了 Turn，消息也送达了，但任务产物没有通过验收。这四个字段描述不同阶段，不能压成一个笼统的 success。

Verifier 在运行前捕获文件 digest，执行前后各检查一次。digest 变化或 Verifier 自己崩溃时，记录为 infrastructure failure。任务没有因此被判 0 分，因为本次验收条件已经失效。

## 第 5 站：失败和重试都进入 ArtifactStore

每次运行得到一个 `AttemptRecord`。第一次看它，只看三个部分：

- `status`：通过、任务失败、超时或运行条件故障；
- `verification`：验收状态与具体 findings；
- `metrics`：usage、延迟和 Pack 自己的指标。

选中的 `TrialRecord` 会引用从第一次到选中 attempt 的所有记录。`ComparisonBlockResult` 保存两臂共同选中的 attempt，`PairResult` 再保存实际 Variant 差异和有效性。

原始 attempt 使用不可覆盖写入。manifest 已存在时也不能被另一份计划替换。Trial、Block 和报告摘要可以原子重建，但它们必须继续指向 digest 匹配的原始记录。

下面这张图从左往右读。实验计划先固定问题，真实 Runner 产生成功、失败和超时记录，Reducer 只读取这些工件，最后生成带 manifest、report 和 digest 的可重建证据。

**图 P11-A｜PicoBench 从冻结计划到可重建报告的证据链**

![](images/P11/img1.jpg)

图下方的橙色说明对应两条规则：失败不会被下一次成功覆盖，console summary 也不能充当正式证据。中途退出后，PicoBench 可以根据 manifest 和已有 attempt 继续；报告仍从磁盘记录重新计算。

## 第 6 站：Reducer 先检查证据，再计算数字

`reduce_experiment()` 从 manifest 取得计划分母，然后逐项读取 Trial、Retrieval、Pair 和 Comparison Block。每条摘要都要和选中的 attempt、`plan_digest` 及原计划一致。

Reducer 会检查：

- 计划中的记录是否全部到达终态；
- Pair 的两臂是否来自同一个 Block attempt；
- observed settings 是否只在声明的 treatment axis 上变化；
- 每个任务是否达到最小有效 Pair 数；
- token 或成本结论需要的 usage 是否完整；
- Provider 与基础设施污染是否仍然存在。

这些检查先于均值、通过率和相对降幅。缺一条 treatment usage 时，Reducer 会留下 finding，并让相应效率测量无效。它不会根据输出文本长度补一个 token 数。

## 第 7 站：报告从原始工件重建

`rebuild_full_report()` 只读取 manifest 和原始记录。它调用 Reducer，执行预先声明的 Claim Rule，然后写出：

```text
summary.json     完整状态、指标和 findings
REPORT.md        便于阅读的报告
cv-metrics.json  只包含通过相应 Claim Group 的指标
```

报告 payload 会计算 canonical digest。相同 manifest 和相同原始工件应得到相同的语义结果，运行时屏幕上打印过什么不会改变它。

## 先分清整场状态和单项状态

`ship_complete` 看整场计划里的证据是否收齐。Reducer 要求所有 planned Trial、Pair、Comparison Block 和 Retrieval Case 都有符合计划的终态记录。

整场 `measurement_valid` 再看所有启用的比较能否共同支持预注册结论。Pair 覆盖不足、两臂设置漂移、usage 缺失或 Provider 污染都会让它失败。

每个能力还会输出自己的状态。例如 Tool/MCP 使用 `tool_mcp.measurement_valid` 和 `tool_mcp.positive_claim_eligible`。这样，即使另一类任务让整场 `measurement_valid=false`，仍能准确说明 Tool/MCP 这一项的比较是否有效、正向门槛是否通过。

当前主 campaign 的真实组合是：

```text
ship_complete = true
measurement_valid = false
positive_claim_eligible = false
```

整场证据已经收齐，但 Context 单项有一条 treatment usage 不完整，所以整场测量状态为 false。Tool/MCP 单项则是：

```text
tool_mcp.measurement_valid = true
tool_mcp.positive_claim_eligible = false
```

第一个值说明 Tool/MCP 比较本身可解释，第二个值说明结果没有满足任务效果门槛。总状态与单项状态使用不同字段，读报告时要先看字段前缀。

## Tool Disclosure 为什么被 Gate 拒绝

冻结实验的 Tool/MCP 单项结果是：

```text
模型可见 Schema 估算 token：宏平均下降 93.4513%
control task pass：23/24
treatment task pass：20/24
```

`93.4513%` 是六个可测量任务上的等任务宏平均估算降幅。它描述模型起初看到的 Schema 变少了，没有描述任务做得更好。

整场 `ship_complete=true`，Tool/MCP 单项 `measurement_valid=true`。task-success 规则检测到通过数从 `23/24` 降到 `20/24`，因此 `tool_mcp.positive_claim_eligible=false`。

下面这张图先看左侧的两项观测，再沿方框向右读。第一框是整场证据完整性，后两框明确带 `tool_mcp` 前缀；正向出口关闭后，底部的 raw records 仍保留。

**图 P11-B｜Tool Disclosure 通过证据完整性与测量有效性后，被任务成功率 Gate 拒绝**

![](images/P11/img2.jpg)

图中最重要的关系是：Schema 变小和任务效果属于两项独立指标。`93.4513%` 会留在 Tool/MCP 单项记录里，任务成功率规则决定它不能进入正向出口。

## 再看三组容易说错的结果

| 实验 | 证据状态 | 可以怎样表述 |
|-|-|-|
| 确定性 Scheduler | 三层 Gate 通过 | 受控本地工作负载中，前台 P95 排队时间中位配对降幅 `86.87%`；10,000 个 accepted requests 中 0 丢失、0 非预期重复、0 未决 Handle |
| 4,160 次真实 Agent Turn | 证据跑完且测量有效，正向 Gate 未过 | 前台端到端 P95 从 `13.57s` 降到 `11.66s`，中位配对降幅 `13.53%`；Verifier 通过 `4,158/4,160`，即 `99.95%` |
| Context 对照 | 证据已保存，效率测量无效 | `23/24` Pair 有完整 usage，一条 treatment usage 不完整，因此不提供 Curator 的正向 token 优化数字 |

确定性 Scheduler 结果只说明这份进程内受控工作负载，不能扩写成生产 SLO、进程崩溃后的 exactly-once 或外部副作用保证。

4,160 次 Turn 全部执行，Provider failure、请求丢失和重复执行均为 0；两次 `marker_missing` 没通过冻结 Verifier。预注册规则要求 `4,160/4,160`，因此表述中要同时保留“全部执行”和“99.95% 验收通过”。

## 失败、取消和续跑怎样处理

### Provider failure

本次 attempt 保存为 `provider_failure`。预算允许时，两臂一起进入下一次 Block attempt；仍无法形成可测量 Block 时，Pair 保留为无效或耗尽状态。

### Task timeout

Provider 与 Runtime 正常，任务在冻结时限内没有完成，可以记录为 `task_timeout`。它属于任务结果，需和 Provider timeout、基础设施 timeout 分开。

### Verifier 变化

执行前后 digest 不一致，Verifier 状态为 `not_run`，Trial 进入基础设施失败。修正验收逻辑后要建立新的实验身份。

### usage 不完整

token 与成本 Claim 无法使用这条 Pair。Reducer 保存缺失原因，不插值，也不把未知值写成 0。

### 中途停止

已写 attempt 和 journal 留在输出目录。相同 manifest 可以从下一条缺失记录继续；计划 digest 不同则拒绝续跑。

### 真实付费阶段未授权

预检在 Provider 调用前停止。没有显式授权时，不会生成一个看似完整的付费实验分数。

## 走完以后，再整理术语

| 日常理解 | 代码名 | 本章中的作用 |
|-|-|-|
| 一次具体尝试 | Trial / Attempt | Attempt 保存每次尝试，Trial 引用被选中的尝试 |
| 一组同条件比较 | Pair | 连接同任务、同重复的 control 和 treatment |
| 两臂一起重试的单位 | Comparison Block | 保证重试后仍在同号 attempt 上比较 |
| 实验唯一变化 | treatment axis | 限制可归因的设置差异 |
| 冻结验收器 | sealed Verifier | 在运行前后检查 digest，再验收任务产物 |
| 原始证据目录 | ArtifactStore | 保存 manifest、attempt、trial、pair 和 journal |
| 重算器 | Reducer | 从原始记录检查分母并计算指标 |
| 正向结论门槛 | Claim Rule / Claim Gate | 决定对应指标能否进入正向出口 |

## 从哪些文件开始读

| 顺序 | 文件与符号 | 只看什么 |
|-|-|-|
| 1 | `benchmarks/picobench/schema.py::ExperimentSpec` | 整场实验冻结哪些信息 |
| 2 | `benchmarks/picobench/packs/tool_mcp/pack.py::ToolMCPPack.definition` | Tool/MCP 的真实任务、实验臂和配对 |
| 3 | `benchmarks/picobench/plan.py::compile_plan` | Trial、Pair 和 Block 怎样展开 |
| 4 | `benchmarks/picobench/harness.py::_run_comparison_block` | 冻结顺序、对称重试和 selected attempt |
| 5 | `benchmarks/picobench/host.py::RuntimeTrialHost.run` | Runtime、Delivery 与终态观察 |
| 6 | `benchmarks/picobench/verifier.py::run_sealed_verifier` | Verifier 前后 digest 检查 |
| 7 | `benchmarks/picobench/artifacts.py::ArtifactStore` | 不可覆盖 attempt 与原子摘要 |
| 8 | `benchmarks/picobench/reducer.py::reduce_experiment` | 完整性、可测量性和单项字段 |
| 9 | `benchmarks/picobench/report.py::rebuild_full_report` | report digest 与指标出口 |

## 用测试验证理解

| 想验证什么 | 先读哪个测试 |
|-|-|
| Runtime、Delivery 和 Provider failure 怎样记录 | `tests/test_picobench_trial_host.py` |
| 报告怎样重建，坏工件怎样被拒绝 | `tests/test_picobench_reporting.py` |
| Tool Schema 与任务成功率怎样共同过 Gate | `tests/test_picobench_tool_mcp_track.py` |
| 4,160 Turn 计划和 Verifier 规则 | `tests/test_picobench_runtime_live_experiment.py` |
| 续跑与付费授权怎样 fail closed | `tests/test_picobench_reproduce.py` |

## 25 分钟代码练习

目标：从实验计划追到 Tool Disclosure 的正向资格。

1. 在 `ExperimentSpec` 中找出 repetitions、identity、execution 和 claim rules；
2. 在 `ToolMCPPack.definition()` 找到真实任务、两个 Variant 和 treatment axis；
3. 进入 `compile_plan()`，写下 8 个任务、2 个 Variant、3 次重复怎样变成 48 个 Trial；
4. 在 `_run_comparison_block()` 找到冻结顺序和两臂共用的 `block_attempt`；
5. 找到 `AttemptRecord` 的 status、verification 和 metrics；
6. 在 `reduce_experiment()` 找到 planned 与 terminal 分母检查；
7. 进入 Tool/MCP reducer，找到 Schema token、task pass 和两个 `tool_mcp.*` 状态；
8. 回到 `rebuild_full_report()`，确认 `cv-metrics.json` 怎样只导出合格组。

完成后回答：

- Provider failure 为什么不能直接记成 task score 0？
- treatment 第二次尝试为什么不能配 control 第一次尝试？
- `ship_complete=true` 时，为什么仍可能没有可写的正向数字？

## 本章复盘

- [ ] 能画出 spec、plan、runner、artifact、reducer、report 的顺序；

- [ ] 能解释 Task、Variant、Pair 和 Comparison Block 的关系；

- [ ] 知道失败和重试为什么都要保留；

- [ ] 能区分任务失败、Provider failure 和 infrastructure failure；

- [ ] 知道报告只从原始工件重建；

- [ ] 能分别解释三个 Gate；

- [ ] 会把 Tool Disclosure 的 `93.4513%` 与 `23/24 → 20/24` 放在同一段；

- [ ] 会把 4,160 次全部执行与 4,158 次 Verifier 通过分开；

- [ ] 不会引用 usage 不完整的 Context token 优化数字。

## 接下来怎么读

- [P12｜Evolver](https://icnoljnkix43.feishu.cn/wiki/Ei3Swl1X8ilP50kgDXhcz95En7f)：候选怎样在冻结评测和人工权限下生成、验收、激活与回滚；
- [简历材料](https://icnoljnkix43.feishu.cn/wiki/IFlbwWf6Bi5a8xkK5k5cK2JunXc)：把通过证据边界的项目结果压缩成简历描述；
- [面试总话术](https://icnoljnkix43.feishu.cn/wiki/H9rewOY10ixocdkYCuwcIHqjneY)：准备项目表达时，再进入逐字话术线。
