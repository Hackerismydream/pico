# Jev 偏好判断实验：实施与架构方案

状态：实验能力，默认关闭。实现不等于已验证收益，不建议直接启用到全部流量。

## 1. 决策与范围

本方案只处理 `Personalizer.classify()` 的一个问题：当个性化已经启用时，能否用专门判断模型识别明确无需询问用户偏好的新请求，从而省掉原有的一次分类模型调用。它不是通用缺失信息判断，不负责模型路由、用户授权、工具执行、任务完成、Memory 写入、发布审批或 Evolver promotion。

选择这个位置，是因为这里确实存在独立 `provider.chat()` 调用。与向 Local Skills 的零远程调用路径追加判断相比，可以明确数出被替换的工作。是否值得保留 Personalizer 本身，则仍由“取消前置分类”的对照组检验。

原始审查基准为 `75795cec37782c929c55a6ff5381084799ac574d`。实施基于 main 的 `697499a36c349bd0989344fd0dcd4282d23d33a9`，对应教程提交的 squash 身份；本次核验的 Runtime 源码与审查基准一致。历史项目状态文档中的指标不是本实验结果。

## 2. 当前调用关系与接入位置

现有链路：Runtime Assembly 创建 Provider 装饰器和 AgentLoop，调用 `configure_personalization()`；用户请求在 `_process_message()` 中创建 Personalizer，读取本地长期偏好和最近四条历史，调用 `classify()`；只有需要澄清时才生成问题并保存 `pending_clarification`。

接入后：

```text
Runtime Assembly
  ├─ CallEfficiency + CallEfficiencyProvider（保留）
  ├─ AgentLoop（保留）
  └─ 可选 JevPreferenceGate（共享、懒创建 HTTP 客户端）

普通 USER 新请求，无 pending clarification，无媒体
  → Personalizer.classify(allow_gate=True)
  → 读取与旧分类器同源的本地偏好和最近历史
  → JevPreferenceGate.assess
       → 不符合资格：旧分类器
       → off：旧分类器
       → shadow：记录“本来会如何判断”，仍调用旧分类器
       → enforce 且满足保守组合：直接返回 needs_clarification=false
       → unknown／低证据／异常：旧分类器
  → 原 Context / 主 Agent / 问题生成 / Session 流程
```

已有 pending clarification 的 recheck 不使用 Jev。带媒体的请求不使用 Jev。Cron 与 Subagent 不参与整个偏好学习流程。后两项不是让 Jev识别来源，而是由 `TurnRequest.origin` 和媒体事实确定。

模块所有权：

| 模块 | 职责 |
| --- | --- |
| `pico/config/personalization.py` | 默认关闭、数据许可、固定版本、deadline、并发和阈值配置 |
| `pico/agent/personalizer/jev_policy.py` | 固定原子问题、Choice 合同校验、保守组合规则 |
| `pico/agent/personalizer/jev.py` | 有界 HTTP 调用、限流、熔断、取消、Trace 和费用记录 |
| `pico/agent/personalizer/personalizer.py` | 消费快速放行或执行原分类器，不改变问题生成合同 |
| `pico/agent/loop/main.py` | 用实际 Origin、媒体和 Session 状态限定调用资格 |
| `pico/cli/_runtime_assembly.py` | 唯一客户端的装配与关闭，关闭客户端后才 flush 费用账本 |
| `pico/call_efficiency/` | 非聊天调用的统一计量、未知费用、与主模型账本合并 |

没有新建通用 Decision Engine，没有把 Jev 当作 `LLMProvider`，没有将 SDK 添加为依赖；复用已有 httpx。

## 3. 输入与原子问题

state 只有当前消息、旧分类器使用的本地长期偏好、同源最近会话的文本表示。不新增 Myna recall，也不读取工作区文件、工具输出或完整 Transcript。所有字段都是被判断的证据，不是控制指令。

当前 Personalizer 的信息边界没有因接入扩大：调用方仍只提供最多四条近期消息；原分类器会截短每条正文至 200 字符。Jev 遇到会被进一步截短的历史、非文本历史、空消息或超过 byte 上限的 state 时退回旧路径，而不是静默截短后放行。更早的历史缺失仍然是现有边界，未宣称已解决。

问题与版本集中定义：`pico.preference-triage.v1`，策略为 `pico.preference-fast-pass.v1`。

| 问题 | Choice |
| --- | --- |
| 任一子需求是否与用户偏好实质相关？ | none / relevant / unknown |
| 所有相关偏好是否均已明确？ | complete / incomplete / not_applicable / unknown |
| 所有未明确偏好是否均可使用不违背用户要求的合理默认值？ | available / unavailable / not_needed / unknown |

仅三组一致结果允许快速放行：无相关偏好；所有相关偏好均已明确；或者所有缺失偏好均可使用合理默认。unknown、矛盾结果、任一低 confidence 或低选中项概率均回旧分类器。

必须校验：问题集合精确一致、type 为 choice、选项集合精确一致、概率是有限数且位于 0–1、总和接近 1、choice 是最大概率项、confidence 类型和范围正确。禁止把字符串、布尔值、NaN 或缺字段当作合格判断。

confidence 与概率阈值分别检查，但不相乘，也不解释为在 Pico 上实测的正确率。0.98 仅是未校准的实验初值；正式使用必须重新标注和验证。Jev 不返回自由文本 domain：不能快速放行时，domain 和问题生成仍由原分类器承担。

## 4. 配置和启用条件

默认：

```yaml
agents:
  defaults:
    enable_personalization: false
    personalization_gate:
      mode: off
```

供已使用 Personalizer 的操作员开展 shadow：

```yaml
agents:
  defaults:
    enable_personalization: true
    personalization_gate:
      mode: shadow
      data_consent: true
      model: jev-1.13.0
      api_key_env: TYPESAFE_API_KEY
      timeout_seconds: 1.0
      max_state_bytes: 12000
      max_concurrent: 2
      requests_per_minute: 60
      min_confidence: 0.98
      min_choice_probability: 0.98
```

还必须有可用的 Memory Backend，并开启持久化 CallEfficiency usage tracking。缺少这些前提，不应为了试用 Jev 而假装存在可节省的现有开销。

`enforce` 额外要求 `policy_digest`，即经操作员审阅的校准证据或受控实验计划的 SHA-256。这个字段用于关联，不会自动验证外部报告，也不是安全授权凭证。实验阶段可以引用冻结实验计划，不得将它写成“生产资格已通过”。实际生产资格由独立结果和人工 review 决定。

API key 只从命名环境变量读取，不放配置正文、报告或 Trace。未选择能力时不创建 HTTP 客户端、不读取凭据、不发请求。关闭 Personalizer 或 Memory 时同样不创建 gate。

## 5. 失败、容量与关闭

| 情形 | 行为 |
| --- | --- |
| 不适用、无 key、关闭、无持久化计量 | 不发 HTTP，使用旧分类器 |
| 并发已满、达到本地分钟限制 | 不排长队，不发 HTTP，使用旧分类器 |
| 总 deadline 到期、HTTP 错误、响应合同错误 | 最多一次 Jev attempt，回旧分类器 |
| 401 / 403 / 422 | 本实例永久熔断，重启并修正配置后恢复 |
| 连续错误达到阈值 | 短期熔断；冷却结束后允许重试 |
| unknown、低置信度、组合矛盾 | 记录成功调用但不采纳结果，回旧分类器 |
| 返回模型版本不匹配、usage 不完整 | 不放行并计入连续失败；仍保留已经发生的调用费用证据 |
| 用户取消 / Runtime 关闭 | 传播取消；不继续调用旧分类器、不追加付费请求 |

固定 HTTPS endpoint，不允许响应重定向，HTTP 客户端不使用环境代理，并请求 identity encoding。正文按原始响应字节流执行上限检查；供应商忽略 identity 而返回压缩数据时拒绝解析，避免自动解压在上限检查前分配超大正文。需要企业代理时应新增明确审查的配置，不能通过任意 endpoint 把用户记忆发送到别处。

shadow 是同步、可计量的一次额外调用，不是零延迟旁路。enforce 未放行时同样增加串行开销。正常关闭先取消并排空 gate 请求，再关闭 HTTP client，最后 flush CallEfficiency，避免请求结束后才写账时账本已关闭。

## 6. 统一费用与可观测性

`CallEfficiency.record_external()` 不伪造聊天 Response，将真实 Jev attempt 记入原 CallLedger。CallRecord 的可选扩展字段为 call_id、call_kind、duration_ms 和 details；原 v1 字段语义不变，既有聊天调用仍使用原入口。

记录请求／实际模型、问题和策略版本、阈值、模式、策略 digest、state 的 hash 与 byte 数、规范化 Choice 分布、是否本来会放行、回退原因、耗时、usage 完整性、Trace / Session / Turn 关联。新增记录不保存用户文本、记忆正文、原始异常正文或凭据。

计价快照来自 2026-09-21 官方 Models 页：仅对核验过的 `jev-1.13.0` 按输入 token 估算费用，输出 token 仍记录但不计价。类型化响应校验失败仍可能已经产生费用，因此 usage 解析与策略采纳分开。未知 usage、未知版本、取消或无法确认的实际模型不能记成免费。

shadow 记录沿用异步 Writer，账本入队不等于落盘，读取 `call-efficiency-ledger-health.json` 才能确认没有缺失。enforce 在快速放行前同步完成该条记录的 locked append、flush 与 fsync；本次持久化失败会回退旧分类器并进入熔断计数。关闭时发现的其他异步写入丢失仍会使实验计量无效。

`TurnOutcome.usage` 仍不是“全部辅助模型调用的总费用”。实验必须汇总完整 CallLedger，并涵盖原分类、问题生成、Curator、主模型、重试和归属本任务的后台学习。不能从内存最近 256 条记录推导完整实验账单。

## 7. 与 Jev 独立的修复

1. 原 Personalizer 只解析 JSON，不校验 needs_clarification 的类型。现在要求严格 bool、有效 domain，并拒绝 Provider error 响应；`"false"` 不再被当成 truthy 的“需要澄清”。
2. Cron 原先会进入分类和事后偏好学习。现在只对真正的 USER Origin 做这两步，防止定时通知被学习成用户偏好。
3. EcoClaw 分类失败返回 `sanity, similarity=0`，原 Router 会继续按正常类别选模。现在无正相似度或非有限结果保留配置默认模型；真正的正相似度 sanity 仍然有效。

这些修复应单列测试和归因。它们不是 Jev 质量提升，实验各组必须共用这些修复后的代码。pending clarification 的“是否新请求”推断、KNN 缺失成本数据、Memory 信息不完整等问题暂不在这个 PR 中重设计。

## 8. 验收与回滚

本 PR 的验收是配置、调用、回退、取消、计量和 Runtime 接线的确定性合同；不包含真实 Jev 效果、中文准确率、费用下降或延迟优化结论。

至少覆盖：off 零请求；shadow 不少调用旧分类器；enforce 合格时恰好省掉一次旧分类；低证据回退；HTTP／格式／版本／usage 异常；限流与熔断；跨 Session 关联；取消；关闭；普通请求、pending、媒体、Cron 和 Memory off；旧分类 Schema 和路由失败修复。

回滚先设置 `personalization_gate.mode=off` 并重启 Runtime；无需改 Provider、Session 或 Memory 数据。独立 bugfix 不随 gate 关闭撤销，如需回滚它们，应通过代码 review 明确执行。

真实实验、四组对照、样本拆分和启用门槛见 [实验交接](../evaluation/jev-personalization.md)。

## 官方依据

- https://docs.typesafe.ai/api — endpoint、Choice、响应和 usage 合同。
- https://docs.typesafe.ai/models — 版本、文本输入、价格、语言与数据处理说明。
- https://docs.typesafe.ai/confidence — confidence 来自概率分布，不是 Pico 校准结果。
- https://docs.typesafe.ai/model-jaggedness/jev-1.13 — 非英文、长 state、推理与对抗输入的限制。
- https://docs.typesafe.ai/introduction — 产品定位。

以上为供应商说明，查阅日 2026-09-21；不能当作本项目已验证的收益。
