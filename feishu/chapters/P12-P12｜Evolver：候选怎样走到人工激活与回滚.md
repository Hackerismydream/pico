# P12｜Evolver：候选怎样走到人工激活与回滚

> P11 说明了一项改动怎样获得可核对的实验结果。P12 再跟一份 Runtime 补丁向前走：模型提出候选后，代码改在哪里、怎样评测、谁确认激活，以及出问题后怎样拿到精确的回滚内容。

## 读前准备

这一章会用到三个已有概念：

- **候选（Candidate）**：一次待评审的代码改动；
- **训练任务（train）**：用于诊断、筛选和比较候选的任务集合；
- **留出任务（sealed test）**：候选选择结束后才揭示结果的任务集合。

本章对应 `origin/main@9914182c7bafa3d3e2a7a5564e792fc9d6d524b7`。运行生命周期、候选分类、证据重算、激活工件和状态迁移均以这份 `main` 源码为准。

## 读完本章，你能回答什么

- 一份候选怎样从冻结 Run 走到可重算证据？
- train 上的三道 Gate 和最后的 sealed test 怎样分工？
- 人类怎样批准激活，并为外部回滚保留精确内容？

## 先跟一份 Runtime 候选走

假设一批 AppWorld 任务里，Agent 连续重复调用同一个失败工具。候选生成器（Designer）提议修改 Runtime：检测到这类重复后，提前停止并生成解释。

后文把这份改动简称为“候选 A”。我们会一直追踪它何时生成、何时被评测、何时留下可审核材料，以及什么时候才能看留出任务。它是否真的更好，要等 train 证据自己回答。

Evolver 需要回答一串具体问题：

```text
这份候选从哪个 base SHA 产生？
它改了哪些文件？
这些文件在允许范围内吗？
改动在什么任务上真的触发过？
candidate 与 control 各跑了多少次？
Provider 故障有没有混进分数？
候选在 train 上是否提升？
sealed test 什么时候揭示？
谁批准进入可激活状态？
回滚要恢复哪些精确字节？
```

Evolver 把这些答案写进 Run、Candidate、Evidence 和 Activation 四组工件。模型负责提出候选，评测代码负责判定证据，人类保留激活决定。

## 先认代码：一份候选的七站

| 阶段 | 主要文件与符号 | 这一站做什么 |
|-|-|-|
| 1. 冻结边界 | `pico/evolver/launch/config.py::RunSpec`、`pico/evolver/launch/contract.py::BenchBundle` | 固定代码快照、任务划分、预算、白名单和任务域入口 |
| 2. 建共同基线 | `pico/evolver/launch/runner.py::_cmd_run` | 预检环境并补齐 train 的 control 结果 |
| 3. 产生候选 | `benchmarks/appworld/evolve/run.py::prepare_candidate`、`pico/evolver/candidate_manifest.py::evaluate_manifest_gate` | 在提交前核对 Manifest，通过后创建隔离子提交 |
| 4. 用 train 比较 | `pico/evolver/orchestrator/gates/pipeline.py::run_gates` | 依次检查测量、真实触发和配对提升 |
| 5. 当轮留证 | `pico/evolver/orchestrator/production.py::_record_candidate_artifacts` | 重算候选证据，创建 before、after、rollback 与初始状态 |
| 6. 结束后开 test | `pico/evolver/launch/runner.py::_unseal_and_report` | rounds 终止或 finalize 后才揭示留出任务结果 |
| 7. 人工决定 | `pico/evolver/activation/artifacts.py::set_activation_state` | 记录 ready、activated 和 rolled_back |

第一遍先读这七站。候选 A 会在第 5 站得到证据和 activation bundle，第 6 站才揭示 sealed test。诊断 Prompt、Bandit 选任务和各个 Orchestrator Node 可以放到第二遍。

## 第 1 站：RunSpec 与 BenchBundle 冻结边界

Run 开始前，`RunSpec` 确定 subject repo、base SHA、工作目录、Bench、模型角色、漏斗预算和任务划分。Bench 自己再给出可以修改的路径白名单。

`validate_whitelist()` 会检查每个允许路径在 base SHA 中确实存在。空白名单或没有命中文件的路径会在运行前失败，避免 Designer 反复生成最后又被全部丢弃的空候选。

`RunMeta` 把生效配置和 `config_hash` 写入 `work_dir/run_meta.json`。同一工作目录恢复时，配置指纹必须匹配。中途更换 base SHA、任务、模型或预算，需要使用新的 Run identity。

JSON 状态通过临时文件和 `os.replace()` 写入。进程在写到一半时退出，下一次恢复不会读到半截 JSON。

### BenchBundle 提供任务环境

一个任务域通过 `build(ctx) -> BenchBundle` 接入。Bundle 第一次阅读只看三件事：

- `run_cold_start`：补齐 control 基线；
- `build_orchestrator`：创建候选生成和评测循环；
- `unseal`：Run 结束后对 sealed test 评分。

这些入口按需执行。`pico evolve status` 可以读取工件并统计进度，不需要顺便发起新的模型调用。

环境预检也由 Bundle 提供。缺安装、subject endpoint 不通、端口占用或白名单失效会在花费任务预算前报告。

## 第 2 站：Cold Start 先建立共同基线

`pico evolve run` 的第一阶段是 Cold Start。它为 train 任务建立 control 测量和失败轨迹，后续候选都和这份基线比较。

Cold Start 以 Trial 为单位幂等。已经完成的 Trial 留在工作目录，再次运行只补缺失项。即使完成计数已经到达总数，Runner 仍会调用 `run_cold_start()`，让 Bench 检查基础设施重跑链是否还有未处理记录。

Cold Start 未完整时，Run 不进入候选轮次。修复环境后使用相同配置重跑即可继续。

## 第 3 站：候选在隔离提交中产生

Orchestrator 从失败轨迹中归纳原因，Designer 生成补丁，补丁应用器（Applier）在隔离工作树中准备修改内容。提交前的 `prepare_candidate` 会先生成 Manifest，再执行候选清单检查（G5）；只有检查通过，才创建 parent 的直接子提交。G5 拒绝的候选不会留下子提交，当前用户 checkout 始终保持不动。

每份补丁会生成 `CandidateManifest`。第一次看 Manifest，只读三组字段：

```text
candidate_id + label
patch_where + target_files
before_sha256 + after_sha256 + patch_digest
```

第一组说明候选是谁，第二组说明改在哪里，第三组把 parent 内容、候选内容和补丁绑定起来。fixture、evaluator 和 activation policy 由 LabelPolicy 补充。

G5 会把 Manifest 和真实补丁重新对照：`patch_where` 是否允许、目标文件是否命中可变面、before/after digest 是否匹配、候选是否真的改变内容、fixture 与 evaluator 是否是 Label 的固定绑定。

## 当前可执行 Label 只有 runtime

Manifest schema 认识六个 Label：

| Label | 当前状态 | 原因 |
|-|-|-|
| `runtime` | supported | 已绑定 AppWorld Runtime fixture、Focused-Fisher evaluator 和精确可变面 |
| `skill` | unsupported | 还没有确定性 Skill routing fixture 与 evaluator |
| `prompt` | unsupported | 还没有确定性 prompt rendering fixture 与 evaluator |
| `policy` | unsupported | 还没有绑定保留 Runtime 的 policy evaluator |
| `model_profile` | unsupported | 还没有 config-only fixture 与 evaluator |
| `route` | unsupported | 还没有 config-only fixture 与 evaluator |

`runtime` 当前只允许修改：

```text
benchmarks/appworld/agent_cli.py
benchmarks/appworld/tool.py
```

它绑定 `appworld_runtime_v1` fixture 和 `appworld_focused_fisher_v1` evaluator，激活策略是 `human_review`。其他 Label 进入 G5 时会得到明确原因并停止，不会改用一个通用模型裁判继续给分。

## 第 4 站：screen、confirm 和三道 Gate 只用 train

通过 Manifest Gate 的候选先做小范围筛选（screen）。它使用较小的 train 子集和较低 K，尽早淘汰明显无效候选。

存活候选再做完整确认（confirm）。confirm 在完整 train 任务上为 candidate 和 control 生成 `TaskEval`。第一次看 `TaskEval`，只读：

- `passes`：通过几次；
- `attempts`：实际观察到几次；
- `failure`：是否有 Provider、infrastructure 或 inconclusive 污染。

`pass_rate` 只用于已经测量的任务。任务缺失、attempt 少于预期 K、Provider failure 和 infrastructure failure 会进入 `MeasurementValidity`，不会直接变成 0 分。

### Gate-f：测量够不够完整

candidate 与 control 的每个任务都要达到 expected K。Provider failure 或 infrastructure failure 让结果进入 failed；缺任务或次数不足进入 inconclusive。任一臂没有形成完整测量，候选停止在这里。

### Gate-b：候选代码有没有真正触发

候选路径调用 `activation_beacon()` 时，会在当前 Trial 的独立 workspace 中留下记录。Gate-b 只把真实触发过的任务纳入归因。

收集器带 `.enabled` 标记时，空 fired set 表示 instrumentation 正常运行，但候选机制一次也没触发，此时候选被拒绝。完全没有接入 instrumentation 时，`fired_tasks=None`，这一道 Gate 显式跳过。

### Gate2：配对结果有没有提升

Gate2 在剩余 eligible tasks 上比较 candidate 与 control。`promoted` 由配对均值是否高于基线决定，`credited_2sigma` 是单独的统计标签。

三道 Gate 的顺序保证先确认两臂证据完整，再缩小归因任务，最后计算提升。无论结果是 accepted、rejected、failed 还是 inconclusive，Gate pipeline 都会产出一份结构化 outcome，交给下一站留存。

## 第 5 站：train Gate 得出结果后，当轮就生成证据和回滚包

`pico/evolver/orchestrator/production.py::_record_candidate_artifacts()` 是这一步的拥有者。它发生在当前 evolution round 内：先调用 `evaluate_candidate_evidence()`，再调用 `create_activation_artifacts()`。此时 sealed test 仍然没有打开。

### Accepted evidence 必须能重新算出来

候选 A 通过 train Gate 后，不能只保存 `accepted=true`。`AcceptedRuntimeEvidence` 保存完整的 candidate/control `TaskEval`、任务 id、expected attempts 和 eligible tasks。其他 outcome 也会保存 EvidenceDecision，并让 activation 初始状态落在 `ineligible`。

首次生成证据时，`evaluate_candidate_evidence()` 还会读取原始 `CandidateOutcome`。其中出现 sentinel regression，候选会被拒绝。写入 accepted evidence 后，`recompute_accepted_runtime_evidence()` 会从 canonical measurements 重放这些检查：

- candidate 与 control 的任务和次数完整；
- 两臂的 MeasurementValidity 都是 measured；
- three-shield Gate 可以重放并得到 promoted；
- eligible tasks 与原 Gate 一致；
- full-train lift 是正的有限数；
- candidate score 能从 TaskEval 重算。

sentinel regression 属于首次生成证据时的输入检查，不是 `AcceptedRuntimeEvidence` 的字段。调用方只传普通 `EvidenceDecision(outcome=accepted)` 会被拒绝；加载 accepted 工件时，还会从保存的 candidate/control 测量再算一次。

### Activation bundle 把候选和回滚放在一起

`create_activation_artifacts()` 为候选 A 创建目录：

```text
activation/<candidate_id>/
├── candidate_manifest.json
├── evidence.json
├── before.json
├── after.json
├── rollback.json
└── activation.json
```

`before.json` 保存 parent 的目标文件内容，`after.json` 保存候选内容，`rollback.json` 必须与 before 的规范字节完全一致。每份 payload 有 SHA-256，`activation.json` 还保存 candidate identity 和状态历史。

accepted 候选必须绑定 `parent_sha` 与 `candidate_sha`。校验会确认 candidate 是 parent 的直接子提交，实际 Git changed paths 与 Manifest targets 完全相同，两个提交中的 blob 也与 before/after 快照一致。

候选 A 到达 `pending_human` 只说明本轮 train 证据和工件已经形成。Orchestrator 仍可依据 train 结果选择 parent、继续后续 rounds；这个状态不会提前揭示 sealed test。

## 第 6 站：rounds 结束后才打开 sealed test

候选诊断、screen、confirm、Gate、证据写入和 parent selection 都只读取 train。Run 正常终止或人工执行 `finalize` 后，Runner 才调用 `unseal`，把留出任务结果写进 retention report。

下面这张图从左往右读。候选在 train 区域内完成 Gate、canonical evidence 和 activation bundle；rounds 结束以后，流程才越过橙色边界，打开 held-out test。

**图 P12-A｜Evolver 从冻结 Run 到 sealed test 的完整生命周期**

![](images/P12/img1.jpg)

图下方还画出了当前 Label 边界：绿色路径只有 `runtime`，并且限定在 AppWorld Runtime 的两个文件；其余 Label 保持 fail closed。

`RunMeta.unsealed_at` 是单向戳记。正常 `run` 看到它后会拒绝恢复同一 Run，避免 test 结果进入后续候选选择。代码保留 `--force` 运维覆盖口；强制继续后，调用方必须把后续 retention 标为无效，不能沿用原来的 sealed-test 口径。

## 第 7 站：人类状态机记录决定

runtime Label 强制人工审查。accepted 候选初始状态是 `pending_human`，允许的路径是：

```text
pending_human → ready → activated → rolled_back
```

`pending_human → ready` 必须记录非空 `human_actor`。每次迁移还保存 reason，加载时会从初始状态重放整段 history。

证据为 rejected、failed 或 inconclusive 的候选从 `ineligible` 开始，没有后续迁移。

下面这张图先看左上角的证据判断，再沿上方状态向右读。中间的 activation bundle 为每个状态提供同一份候选、证据和回滚身份，右下角的虚线框表示外部应用动作。

**图 P12-B｜人工激活状态、回滚记录与外部应用动作的边界**

![](images/P12/img2.jpg)

`set_activation_state()` 只更新 activation 工件，调用方 checkout 保持不动。代码层没有要求人工状态迁移必须等到 unseal 之后；若团队规定先完成整场 Run 再批准，这是外部运维流程的顺序。

`activated` 表示激活决定已经记录，不表示 Git checkout、安装 wheel、Gateway 重启或流量切换已经发生。真正应用候选时，外部流程还要核对目标环境身份，应用 candidate commit，运行健康检查，再记录 `activated`。回滚也要先应用 `rollback.json` 对应的 before 内容并验证运行环境，然后记录 `rolled_back`。

## 一条候选的完整时间线

把前面的部件连起来，Runtime 候选会经历：

```text
读取 RunSpec，固定 base SHA、train/test、预算和白名单
→ Bench 预检环境
→ Cold Start 补齐 control 基线
→ 从 train 失败轨迹诊断问题
→ Designer 生成补丁
→ Applier 在隔离工作树中准备修改内容
→ CandidateManifest 绑定修改面与 digest
→ G5 在提交前检查 LabelPolicy 和目标文件
→ 通过后形成 parent 的直接子提交
→ screen 在小 train 子集上筛选
→ confirm 在完整 train 上测 candidate/control
→ Gate-f 检查测量有效性
→ Gate-b 检查真实触发
→ Gate2 比较配对提升
→ 从 canonical candidate/control 测量生成 accepted evidence
→ 在当前 round 创建 activation bundle 和 pending_human 状态
→ Orchestrator 依据 train 结果选择 parent，并继续剩余 rounds
→ Run 终止或 finalize
→ unseal held-out test
→ 写 retention report
```

人工审查可以在 activation bundle 形成后推进 `pending_human → ready`。外部流程真正应用并验证候选后，再记录 `activated`；环境出现问题时，应用 before 快照、验证环境并记录 `rolled_back`。

## 失败、中断和恢复分别留下什么

### 环境预检失败

Run 在付费任务前停止，报告缺安装、端口、endpoint 或白名单问题。修正后可以重新执行检查。

### Cold Start 中断

完整 Trial 保留，再次运行补齐缺失项。配置指纹必须保持一致。

### Evolution round 中断

已完成轮次写进 journal。恢复时从 durable state 继续，已完成候选不会重新解释。

### Provider 或 infrastructure failure

Bench 的重跑链可以尝试恢复。仍然存在的失败让 MeasurementValidity 进入 failed 或 inconclusive，候选不能 promotion。

### 配置漂移

同一 work_dir 拒绝继续。改变任务、模型、预算或 base SHA 时，应使用新的 Run identity。

### Unseal 写报告时中断

Runner 在写 retention report 前先写 unseal stamp。若随后退出，Run 仍是 final；`finalize` 可以重建缺失报告，不会恢复候选选择。

### 工件 digest 不匹配

Manifest、evidence、snapshot 或 activation record 任一校验失败，加载和状态迁移都会停止。人工确认不会跳过完整性检查。

### 非法状态迁移

`pending_human → activated`、`activated → ready` 和 `ineligible → ready` 都会被拒绝。状态必须逐步向前。

## 当前证据能支持到哪里

当前源码和确定性测试覆盖 Run 配置、恢复、三道 Gate、Manifest、证据重算、Git 绑定、激活状态和回滚工件。这些证据说明生命周期与权限合同可以重复验证。

当前运行面只有 AppWorld `runtime` Label。完整规模的真实模型多轮 Evolution Run 尚无可进入简历的效果数字，确定性 fixture 结果也不等同于真实任务提升。

Evolver 的当前交付物是可审查候选、可重算证据和人工激活工件。发布到哪个 checkout、安装物或 Gateway，由外部有权限的流程执行并单独验证。

## 走完以后，再整理术语

| 日常理解 | 代码名 | 本章中的作用 |
|-|-|-|
| 一次完整演进实验 | Evolution Run | 固定配置后完成基线、候选轮次和 unseal |
| 任务域接入包 | BenchBundle | 提供基线、评分、轨迹、任务划分和环境预检 |
| 待评审改动 | Candidate | 在隔离工作树中产生的子提交 |
| 候选身份证明 | CandidateManifest | 绑定 Label、目标文件、内容 digest 和 evaluator |
| 每任务测量 | TaskEval | 保存通过数、尝试数和失败类型 |
| 测量分类 | MeasurementValidity | 区分 measured、failed 和 inconclusive |
| 真实触发记录 | activation beacon | 为 Gate-b 提供归因任务集合 |
| 可重算正向证据 | AcceptedRuntimeEvidence | 保存 candidate/control 的 canonical measurements |
| 激活工件包 | activation bundle | 保存证据、before、after、rollback 和状态历史 |

## 从哪些文件开始读

| 顺序 | 文件与符号 | 只看什么 |
|-|-|-|
| 1 | `pico/evolver/launch/config.py::RunSpec` | Run 固定的配置 |
| 2 | `pico/evolver/launch/state.py::RunMeta` | config hash、原子写与 unseal stamp |
| 3 | `pico/evolver/launch/runner.py::_cmd_run` | Cold Start、rounds、unseal 的顺序 |
| 4 | `benchmarks/appworld/evolve/run.py::prepare_candidate` | Manifest/G5 与创建子提交的先后 |
| 5 | `pico/evolver/candidate_manifest.py::LABEL_POLICIES` | 六个 Label 的真实支持面 |
| 6 | `pico/evolver/orchestrator/gates/pipeline.py::run_gates` | Gate-f、Gate-b、Gate2 |
| 7 | `pico/evolver/orchestrator/production.py::_record_candidate_artifacts` | evidence hook 位于 round 内 |
| 8 | `pico/evolver/candidate_evidence.py::evaluate_candidate_evidence` | 首次证据判断与 sentinel 检查 |
| 9 | `pico/evolver/candidate_evidence.py::recompute_accepted_runtime_evidence` | canonical measurements 怎样重算 |
| 10 | `pico/evolver/activation/artifacts.py::create_activation_artifacts` | commit、snapshot、digest 和初始状态 |
| 11 | `pico/evolver/activation/artifacts.py::set_activation_state` | 单向状态迁移与人工字段 |

## 用测试验证理解

| 想验证什么 | 先读哪个测试 |
|-|-|
| Run 生命周期、配置漂移和恢复 | `tests/test_evolver_launch.py` |
| 跨进程中断、续跑、状态和 finalize | `tests/integration/test_evolver_lifecycle_e2e.py` |
| LabelPolicy、Manifest 与 G5 | `tests/test_evolver_candidate_manifest.py` |
| accepted evidence 怎样从测量重算 | `tests/test_evolver_candidate_evidence.py` |
| 三道 Gate 和 failure 分类 | `tests/test_evolver_gates.py` |
| activation bundle、状态机与 rollback | `tests/test_evolver_activation_artifacts.py` |

## 30 分钟代码练习

目标：判断一份 runtime 候选为什么能进入 `pending_human`，以及为什么还没有改变当前 checkout。

1. 在 `LABEL_POLICIES` 找到 runtime 的 mutable paths、fixture、evaluator 和 activation policy；
2. 在 `evaluate_manifest_gate()` 找到 target file 与 digest 检查；
3. 在 `measurement_validity()` 找到 Provider failure 和 attempts 不足的分支；
4. 在 `run_gates()` 按顺序标出 Gate-f、Gate-b 和 Gate2；
5. 在 `_record_candidate_artifacts()` 确认证据与 activation bundle 在 round 内生成；
6. 在 `recompute_accepted_runtime_evidence()` 找到 canonical measurements 重算；
7. 在 `create_activation_artifacts()` 找到 `rollback.json` 怎样由 before 生成；
8. 在 `_cmd_run()` 找到 rounds 结束后才调用 unseal 的位置；
9. 在 `_initial_state()` 找到 accepted runtime 候选的初始状态；
10. 在 `set_activation_state()` 找到 docstring 和 `human_actor` 检查。

完成后回答：

- 把 candidate label 改成 `prompt` 会在哪一步停止？
- Provider failure 为什么不会让 candidate 以较低分继续比较？
- activation record 已是 `activated` 时，还要核对哪些外部状态？

## 本章复盘

- [ ] 能画出 Cold Start、rounds 和 unseal；

- [ ] 知道 train 与 sealed test 在什么时候使用；

- [ ] 能解释隔离工作树、parent SHA 与 candidate SHA 的关系；

- [ ] 知道当前唯一 supported Label 是 runtime；

- [ ] 能说出两个 runtime mutable paths；

- [ ] 能按顺序解释三道 Gate；

- [ ] 知道 accepted 证据必须从 candidate/control 测量重算；

- [ ] 知道 evidence 与 activation bundle 在 train round 内生成，unseal 在 Run 结束后发生；

- [ ] 能说明 before、after 和 rollback 的关系；

- [ ] 能画出 `pending_human → ready → activated → rolled_back`；

- [ ] 知道状态迁移不会切换 checkout 或部署 Gateway；

- [ ] 不会把确定性 lifecycle 测试写成真实任务提升。

## 接下来怎么读

- [面试总话术](https://icnoljnkix43.feishu.cn/wiki/H9rewOY10ixocdkYCuwcIHqjneY)：把 Runtime、评测和 Evolver 串成一条完整项目讲法；
- [面经问题映射](https://icnoljnkix43.feishu.cn/wiki/NrUbwRyGeiUd1pk5R8WcxKuNn50)：按具体问题跳到对应章节；
- [简历材料](https://icnoljnkix43.feishu.cn/wiki/IFlbwWf6Bi5a8xkK5k5cK2JunXc)：只选有证据边界的能力和数字。