<!--
Source: https://icnoljnkix43.feishu.cn/wiki/JT4Vw4R8ri5oHXkfWducChKCnqg
Node token: JT4Vw4R8ri5oHXkfWducChKCnqg
Document ID: ZREMdGv39ozXY0x2j5TcddvSnmh
Revision: 1
Fetched: 2026-09-02T09:12:58.827Z
Snapshot purpose: read-only source material for the PicoBench tutorial prompt.
Feishu-hosted images are intentionally omitted from Git; their alt text is retained.
-->
# P09｜减少 Agent 成本的实践：Pico 如何用 CallEfficiency 先算清，再优化

一个 Coding Agent 刚刚完成任务：它读了代码，调用了工具，修复了问题，最后给出答案。界面上能看到最后一次模型响应的 usage，看起来这次任务并不贵。

但沿着运行记录往回看，事情没有这么简单。Agent Loop 为完成任务推进了多次 Iteration；其中一次模型调用超时后重试，另一次切换到了 fallback 模型。最终响应只保留了最后一次成功调用的结果，前面已经发生的模型尝试并不会因此消失。

这时如果要“减少 Agent 成本”，应该优化最后一次调用，还是整个任务？

本章只讨论 Agent 的 **模型 Provider 调用成本**。工具 API、机器资源、存储和人工运营同样构成完整 TCO，但不属于 CallEfficiency 当前负责的边界。

我们会沿着同一个任务完成一条闭环：

```text
任务完成
→ 收集全部 Provider attempts
→ 判断 usage 与账本是否完整
→ 找到主要成本来源
→ 修改调用或缓存策略
→ 重新运行相同任务
→ 同时验证任务成功与成本变化
```

这条路径背后的判断很简单：

> **降低成本之前，必须先知道成本发生在哪里；优化成立之前，必须证明任务结果没有因此变差。**

## 先别急着优化最后一笔 usage

一个自然的做法，是把最终响应里的 Token 数当作这次任务的成本。若数字太大，就缩短 Prompt、换便宜模型或打开缓存。

这个做法需要四个假设同时成立：

1. 一个 Turn 只发生一次模型调用；
2. 最终响应的 usage 覆盖了整个 Turn；
3. 失败、重试和 fallback 没有额外成本；
4. Token 下降时，任务质量与成功率保持不变。

Agent Loop 恰好会打破这些假设。模型可能先请求 Tool，拿到结果后再次思考；上下文溢出可能触发恢复调用；临时错误可能重试；主模型失败后还可能切换备用模型。一次成功 Turn 可以包含多次模型尝试，而一次失败 Turn 同样已经消耗资源。

因此，本章真正优化的不是“某一条响应有多便宜”，而是：

> **在任务成功、质量和可靠性边界没有退化的前提下，降低每次验证成功任务的 Provider 成本。**

这一定义会改变后面的判断方式。

- Token 下降，但任务更容易失败，不算有效优化。
- 单次调用更便宜，但带来更多 retry，整个 Turn 可能更贵。
- cache hit rate 提高，但账本漏记了一部分 attempt，不能据此宣布节省。
- 一次任务失败了，它已经发生的调用成本仍要保留在实验分子里。

成本优化不是找一个更小的数字，而是让相同结果使用更少的可计价资源。

## 一次 Turn 里，钱到底在哪里发生

上一章已经看到 Agent Loop 怎样在“模型判断、工具执行、结果写回”之间循环。现在要把这条循环拆到计费事实所在的粒度。

**Turn** 是 Agent 对一条输入完成的一整轮反应。它描述用户看到的任务边界：成功、失败或取消。

**Iteration** 是 Agent Loop 的一次推进。一次 Iteration 通常包含模型判断，也可能跟随一次或多次 Tool 执行。Tool 结果写回 history 后，下一次模型判断进入新的 Iteration。

**逻辑模型调用** 是代码发起的一次调用意图。调用者只写一次 `chat_with_retry`，内部策略却可能展开重试和 fallback。

**Provider attempt** 是一次真正越过 Pico Provider 适配器边界的 dispatch。主模型第一次尝试、同模型 retry、备用模型 fallback，都是不同的 attempt。

> 配图说明：一个 Turn 怎样展开成多次 Provider attempt。原始飞书图片未纳入 Git 快照。

图中最值得记住的不是 attempt 数量，而是层级关系：一个 Turn 可以有多个 Iteration，一个逻辑调用也可以展开成多个 Provider attempt。Tool 本身不产生模型 Token 账单，却会改变下一次 attempt 的输入。

最终响应会把前面的控制流折叠起来。Provider attempt 才是 CallEfficiency 用来记录成本事实的基本粒度。

这里还有一条观察边界。CallEfficiency 能看见 Pico Provider 适配器暴露的 attempt；如果底层 SDK 在一次 dispatch 内部又进行了没有暴露 hook 的 transport retry，Call Record 无法证明里面实际发生了多少次 HTTP 请求。后文的 attempt 都指 **Pico 在 Provider 边界可观察到的 attempt**。

## Pico 把记账层放在 Provider 门口

Pico 的 Runtime Assembly 创建一份共享的 CallEfficiency，再用 `CallEfficiencyProvider` 装饰真实 Provider。主 Agent、Subagent、Context、Personalizer 和 Memory 发起的模型调用都会经过这层装饰器。TUI 在运行期替换底层 Provider 时，稳定的装饰器只更新 delegate，观察边界保持不变。

这个位置同时满足两件事。

第一，它位于实际模型已经确定的地方。fallback 从主模型切到备用模型后，CallEfficiency 会针对新的 attempted model 重新判断请求与缓存策略，而不是把主模型的计划机械地沿用下去。

第二，它能看见每个 attempt 的开始和终点。一次逻辑调用若经历“主模型失败、主模型 retry、备用模型成功”，ledger 会得到三条独立记录。Agent Loop 最后拿到的是成功响应，CallEfficiency 保留的是这条成功路径付出的全部可观察尝试。

正常路径可以压缩成八步：

```text
Agent Loop 发起逻辑调用
→ CallEfficiency 准备请求
→ Provider dispatch
→ Provider 返回响应与 usage
→ CallEfficiency 归一化 usage
→ 根据 accounting model 查价
→ 生成 Call Record
→ 异步写入 ledger
```

CallEfficiency 因此不是 Agent Loop 的第二套执行器。它保留原有 Provider 接口，在调用前准备请求，在调用后生成证据，真正的模型请求仍由底层 Provider 完成。

## 一条 Call Record 怎样把账算清

Call Record 是一次已观察到的 attempt 收据。读者不需要先背下整个数据类，只需要沿着一次对账会提出的问题去看。

| 对账问题 | 对应事实 | 为什么不能合并 |
|-|-|-|
| 调用者原本想用哪个模型 | `requested_model` | 保留调用意图 |
| 这次真正尝试了哪个模型 | `attempted_model` | retry 与 fallback 在这里分开 |
| Provider 最终报告哪个模型 | `actual_model` | 路由服务可能返回实际模型 |
| 应该按哪个命名空间查价 | `accounting_model` | OpenRouter 等路径需要保留计价归属 |
| 这次调用发生了什么 | `outcome`、`finish_reason`、`error_category` | 区分成功、错误、取消和不完整流 |
| Token 是否足够支持估价 | `usage.complete`、`findings` | 缺失或歧义数据不能假装完整 |
| 成本是否可计算 | `estimated_cost_usd` | `null` 表示未知，数值零才表示已知为零 |
| 这条记录属于哪个任务 | `trace_id`、`turn_span_id`、`session_key` | 把多个 attempt 重新归属到 Turn |

四个模型字段看起来相似，却解决不同问题。假设调用者请求一个 OpenRouter 模型，fallback 又切换了模型，Provider 最终还返回了路由后的真实名称。如果只留下一个 `model` 字段，后续很容易把备用模型的 Token 套进主模型价格。

### usage 必须先归一化

不同 Provider 对输入 Token 的报告口径不同。

- DeepSeek、OpenAI 和 OpenRouter 路径可能把 cache read 包含在输入总量中；
- Anthropic 通常把 fresh input、cache read 和 cache creation 分开报告；
- 某些未知模型只返回一个总输入，却没有说明缓存 Token 是否已经包含在内。

CallEfficiency 将这些字段归一化为 fresh input、cache read、cache write、output 和 reasoning 等维度。只有字段齐全、数值有效、Provider 语义明确时，`usage.complete` 才会为 true。

例如，DeepSeek 报告输入总量 1000，其中缓存命中 800、未命中 200，输出 50。已知 DeepSeek 的输入总量包含缓存命中，因此归一化后的 fresh input 是 200，而不是再次把 1000 与 800 相加。

若换成一个缓存语义未知的模型，同样的字段组合无法安全拆分。CallEfficiency 会留下 `input_token_semantics_ambiguous`，把 usage 标记为不完整，并停止成本估算。

这条规则贯穿整章：

> **能证明多少，就记录多少；无法确定的成本保持未知。**

### estimate 仍然不是 invoice

usage 完整后，CallEfficiency 使用 `accounting_model` 查询价格并计算 `estimated_cost_usd`。价格不存在时，它会记录 `pricing_unavailable`，成本继续保持未知。

即使拿到非空估算，它仍然只代表 Pico 按当前价格目录与归一化口径计算的 estimate。阶梯价、免费额度、税费、路由加价、账期调整和供应商最终认定的计费事件，都属于 Provider 账单系统。

Call Record 当前也没有 invoice item id 和不可变价格快照身份。它能帮助我们重建 Runtime 成本事实，不能单独完成财务核销。

## 算不清时，系统为什么选择留下未知

成本记录最容易在异常路径里失真。正常响应通常带回 usage；失败、取消和流式中断却可能只留下“调用已经开始”这一事实。

### retry 与 fallback

同一模型 retry 两次，会形成两条 attempted model 相同的记录。切换 fallback 模型后，新记录拥有新的 `attempted_model`，请求也会按新模型重新准备。

错误 attempt 可能带有完整 usage，也可能没有。没有 usage 时，Pico 无法判断错误发生在 Provider 接收请求之前还是之后，也无法推断供应商是否计费。它记录“attempt 已发生，成本未知”，不会把失败调用写成零成本。

### stream 与取消

当前 Agent Loop 的流式路径不执行 retry 或 fallback，一条 stream 对应一个可观察 attempt。正常读到结尾时，最后收到的 usage 用于落账；发生异常会记录 error；任务取消会记录 cancelled；消费者提前关闭生成器会记录 incomplete。

已经显示出部分文字，只证明 stream 产出了内容。若最终 usage chunk 尚未到达，Call Record 仍然存在，但成本不能估算。

取消发生得更早时，边界也不同。attempt 尚未进入 Provider 装饰器之前被取消，可能没有 Call Record；attempt 开始后被取消，CallEfficiency 会尽力保留 cancelled 记录。两种结果反映的是取消发生在不同生命周期位置。

### 回答成功与证据落盘是两个状态

如果 Provider 响应必须等待磁盘写入，记账就会进入用户延迟路径。CallEfficiency 先在内存接受记录，再通过有界队列交给后台 writer 批量追加 JSONL。

这个取舍让响应可以先返回，也带来新的验收问题：模型调用成功，不代表证据已经可靠持久化。因此对账时还要检查 `call-efficiency-ledger-health.json`。

- `healthy` 且 accepted 等于 persisted、lost 为零，说明被 ledger 接受的记录都已落盘；
- `degraded` 表示已知丢失或 writer 故障；
- health 文件缺失时，持久化状态无法判定；
- 强制杀进程或机器掉电不提供零丢失保证。

干净关停时，Runtime 会先用 `begin_close()` 封住新的后台 Provider 工作，等待已经进入的 AgentLoop 后台任务收口，再关闭 CallEfficiency ledger，最后停止 Memory backend。`finish_barrier()` 保证调用者取消不会把清理停在半途中。

账本健康并不证明 SDK 内部没有隐藏 retry，也不证明 Call Record 与供应商发票一一对应。它只回答一个更窄、但非常重要的问题：**CallEfficiency 已接受的证据有没有完整落盘。**

## 账算清以后，才知道该优化哪里

现在可以把“Agent 太贵”拆成几个可行动问题。

**调用次数过多。** Agent Loop 可能进行了无效 Iteration，临时错误可能触发重试风暴，错误的 fallback 策略也会重复发送完整上下文。CallEfficiency 能把这些 attempt 暴露出来，但是否继续调用由 Agent Loop 与 Provider retry 策略决定。

**单次输入过大。** history、Tool Schema、稳定系统指令和工具结果会在后续调用中反复进入上下文。CallEfficiency 记录 Token 与 cache usage；上下文裁剪、Tool disclosure 和 Memory 策略由各自 owner 决定。

**模型选择不合适。** 高价模型可能被用于不需要它的任务，便宜模型也可能因为成功率低、retry 多而让单位成功成本上升。CallEfficiency 提供实际 attempted model 与估算成本，路由系统负责模型选择。

**稳定前缀没有得到缓存收益。** 这是 CallEfficiency 可以直接参与请求优化的部分。`observe` 模式只观察，不改写请求；`optimize` 模式会根据 Provider 能力准备缓存请求。

> 配图说明：成本优化要找到正确的 owner。原始飞书图片未纳入 Git 快照。

| 能力 | CallEfficiency 的角色 | 真正 owner |
|-|-|-|
| 记录 retry、fallback 与 stream 成本 | 直接观察并生成 Call Record | CallEfficiency |
| 发现 Iteration 过多 | 提供 attempt 与成本证据 | Agent Loop |
| Anthropic 显式缓存规划 | 在 `optimize` 下准备 `cache_control` | CallEfficiency 与 Anthropic Provider 能力边界 |
| DeepSeek/OpenAI 自动缓存 | 观察 Provider 返回的 cache usage | Provider |
| 模型路由与 fallback 选择 | 提供实际模型与成本反馈 | Routing / Provider retry policy |
| 判断任务是否成功 | 不负责 | verifier / evaluation |
| 供应商最终账单 | 不负责 | Provider billing system |

对于支持显式缓存控制的 Anthropic 模型，CallEfficiency 会尊重合法的外部 marker；格式错误或超过上限时，先清理再重新规划。对于 DeepSeek、OpenAI 等自动缓存 Provider，请求保持原样，Pico 把策略记录为 `provider_automatic`。缓存是否存储、是否命中、命中多少和如何计费，仍由 Provider 决定。

因此，CallEfficiency 不是一个自动省钱开关。它直接拥有少量请求优化动作，更重要的作用是让成本驱动因素能够被定位，并把反馈交给真正拥有决策权的子系统。

## 一次真实实践：稳定前缀有没有降低单位成功成本

Pico 当前的 DeepSeek V4 Flash campaign 展示了怎样把“再优化”做成一次可验证实践。

实验问题不是“缓存命中率能有多高”，而是：

> 在相同冻结任务上，保持请求前缀稳定，是否能在任务全部验证成功的前提下，降低每次成功任务的估算 Provider 成本？

每个 Comparison Block 执行同一个任务的两种策略：

| 策略 | 请求行为 | 实验作用 |
|-|-|-|
| `prefix_disrupted` | 每次 Provider call 前改变 system 与 Tool Schema 的前导字节 | 破坏稳定前缀的负对照 |
| `prefix_stable` | 保留 Pico 正常的稳定请求前缀 | treatment |

两组都使用 DeepSeek 自动缓存。Pico 没有创建 KV Cache，也没有通过 `cache_control` 强迫 DeepSeek 命中；实验改变的是请求前缀是否稳定。

campaign 冻结了模型、Provider、Tool 集、Context 预算、workspace fixture、Prompt 和 retry 限制，并禁止 fallback。它覆盖四类 workload、12 个任务、三次重复与两种策略，共形成 36 个 Comparison Blocks、72 个 Trials 和 504 次真实 Provider calls。

主指标是：

```text
cost_per_verified_success
= 所有有效 Trial 的估算成本总和 / verifier 成功数
```

失败任务已经产生的成本仍留在分子里。Positive Claim 还要求所有计划 block 有效、usage 与成本完整、实际模型没有漂移、treatment 成功率不回退、ledger 健康，并且配对成本降幅的置信区间下界高于零。

当前冻结结果中，两组任务验证成功率都为 100%。稳定前缀的保守 cache hit rate 为 74.0478%；每次验证成功任务的估算成本从 USD 0.008356 降到 USD 0.002311。task-clustered 配对估计降幅为 72.0750%，95% 区间为 68.8471% 到 75.0961%。

这个结果支持一条有边界的结论：**在这组冻结 workload 与 DeepSeek 自动缓存条件下，保持 Pico 请求前缀稳定，降低了每次验证成功任务的估算成本。**

它不等于供应商发票核销，也不能外推成所有生产任务的节省率。实验使用的 `prefix_disrupted` 是负对照，不是可部署的旧版本。完整原始报告保存在 Git 之外的证据目录，仓库只保留实验契约、摘要、digest 与重放入口。

TokenWise 这个名称在这里仅保留为历史实验沿革。当前 Runtime、配置规范键、Provider decorator 与事实账本都属于 CallEfficiency。

## 回到开头：下一次成本异常应该怎么查

现在回到那次“最终 usage 看起来不贵”的 Coding Agent 任务。

假设沿同一个 `trace_id` 与 `turn_span_id` 找到五条记录：

| attempt | 发生了什么 | usage 状态 | 能得出的成本结论 |
|-|-|-|-|
| A1 | 主模型超时 | 不完整 | attempt 已发生，成本未知 |
| A2 | retry 成功返回 Tool Call | 完整且可定价 | 已知估算为 C2 |
| A3 | 下一次逻辑调用报错 | 不完整 | attempt 已发生，成本未知 |
| A4 | fallback 生成答案 | 完整且可定价 | 已知估算为 C4 |
| A5 | 边界后的额外合成 | 完整且可定价 | 已知估算为 C5 |

最终响应只描述 A5，整个 Turn 的可辩护说法则是：Pico 观察到五次 Provider attempt，其中三次有完整 usage 与可用价格，已知估算小计为 C2 + C4 + C5；两次成本未知；记录集合是否完整还要结合 ledger health；这些估算尚未与供应商账单核销。

接下来才轮到优化。若主要成本来自反复 retry，应检查错误分类和 retry/fallback 策略；若来自每次都重复的大段输入，应检查 Context 与缓存；若便宜模型导致更多失败，应回到每次验证成功任务的成本，而不是只比较单价。

> 配图说明：CallEfficiency 的成本优化闭环。原始飞书图片未纳入 Git 快照。

以后面对任何高成本 Agent Turn，都可以沿着同一组动作排查：

1. 用 `trace_id` 与 `turn_span_id` 定位 Turn；
2. 收集全部 Call Records，保留失败、取消和不完整 attempt；
3. 检查 ledger health，判断记录集合是否完整；
4. 只汇总 usage 完整且可定价的记录，未知成本单独列出；
5. 找到调用次数、输入规模、模型、fallback 或缓存中的主要驱动因素；
6. 把改动交给真正拥有决策权的 owner；
7. 在相同任务、成功标准和证据要求下重新运行；
8. 同时报告任务结果、成本变化与仍然未知的边界。

CallEfficiency 的价值到这里才完整显现：它先让每一次模型尝试可见，再让优化有起点，让“省了多少钱”有可以接受反驳和复核的证据。
