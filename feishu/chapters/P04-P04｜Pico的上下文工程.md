# P04｜Pico的上下文工程

大语言模型的一切推理能力都建立在一个前提之上：上下文窗口。Agent 在每一轮对话中，都要把系统指令、工作记忆、技能描述、会话历史、工具调用结果和当前请求打包发给模型。随着对话推进，这个历史不可避免地膨胀，最终撞上模型上下文窗口的天花板。

可以把上下文窗口想象成一块有限大小的白板。Agent 的所有工作记忆——对话历史、工具结果、中间决策——都必须写在这块白板上。白板空间用完时，你必须擦掉旧内容才能写新内容。关键问题是：**这一轮到底该让模型看到什么？谁决定哪些信息进入？以什么结构进入？占多少预算？哪些内容必须成组保留？失败时怎样退回一条仍可运行的路径？**

这个问题在 Agent 里比一次性问答尖锐得多。普通问答发一次请求就结束；Agent 在循环里调用工具，工具结果又成为下一次调用的历史，每一轮都在制造新的上下文。如果每次都把此前所有日志原样堆回去，真正关键的 `tool_call_id` 配对关系反而会淹没在噪声里。

![](images/P04/img1.jpg)

# 一、最朴素的组装：把所有材料塞进去，然后看它怎么坏

最朴素的组装方式是把所有材料拼成一个巨大的 system prompt：系统指令、全部历史、全部工具 schema、当前请求，一股脑塞进 `messages`。做法简单直观，但会带来五个问题。

## 1. 预算不可控

窗口要为模型输出预留空间，系统指令、工具 schema、当前任务和历史会竞争同一份输入预算。全塞进去的后果是成本线性涨、首 token 延迟变高、信噪比一路下降。你以为 `messages` 里只有 system、history、user 三个槽位，但工具定义虽然走 Provider 的独立 `tools` 字段，它照样占输入预算——工具是第四个槽位，只是走旁路。

## 2. 工具配对被拆散

模型与工具之间存在结构契约：assistant 消息发出 `tool_calls`，tool 消息带着 `tool_call_id` 返回结果。如果只保留 Tool Result、丢了发起调用的 assistant 消息，Provider 会看到一个没有父调用的孤儿结果；如果只保留 Tool Call、丢了结果，会看到一个悬空的调用。两种情况都可能让 Provider 拒绝请求。历史一旦进入工具交换的中间，协议就破了。

## 3. Session 不等于 Context

Session 保存完整、按序追加的会话记录，它是候选材料，不等于本轮 Context。Session 里存着、数据库里存着、向量检索能查到，都还没进入 Context——只有被选进这一轮 `messages` 的消息，模型才能看见。存了不等于看见了，这是最容易混淆的一层。

## 4. 顺序敏感

模型"接受长输入"和"稳定利用每个位置的信息"是两回事。*Lost in the Middle* 显示，相关信息落在长上下文中部时，部分模型的使用效果明显下降；RULER 也显示，长度和任务复杂度增加后，模型的实际长上下文表现可能下滑。窗口长度只是容量上限，不代表注意力质量。系统前缀的顺序、历史的排序，都会改变模型实际用得上多少。

## 5. 一刀切

用户贴的代码、约束和目标，是任务的输入意图；工具输出只是系统执行过程里的观测结果。它们不应该被同一种规则处理。用户说"不要改公共 API，只修内部实现"，这句话如果被压掉，边界就没了。当前用户消息每一轮恰好出现一次，它不是可插拔的 Segment——它是结构的固定件。

# 二、主流 Agent Harness 怎么组装上下文

上下文管理不是 Pico 独有的问题，主流 Harness 各自给出了答案。

## Claude Code：先算预算，再分级清理

Claude Code 先把可用窗口算清楚：模型总窗口减掉预留输出 token，剩下的才是当前轮真正能用的上下文预算。然后它根据剩余空间把会话分成几个状态：安全、预警、自动压缩、阻塞——模型调用前系统就能判断当前上下文是否健康，而不是等 provider 报错后才补救。

它的压缩分四档，越往后成本越高：**Snip** 直接清掉旧工具结果，不调用 LLM，只把内容替换成占位标记，token 省下来了，消息链和工具调用 ID 还在；**MicroCompact** 处理长时间暂停后的上下文，清掉过期的旧工具输出；**Collapse** 在上下文压力变高时主动重组消息，尽量保留仍有价值的原始细节；**AutoCompact** 最后才用 LLM 做对话摘要，并把压缩边界、摘要、保留消息重新拼成新的上下文。整个顺序按成本排：先清低风险内容，再做结构调整，最后才让 LLM 摘要。

对 Pico 的启示：**压缩是一个成本阶梯，不是一道开关。**旧工具输出最占空间也最容易安全移除，用户需求、关键决策、错误原因应该尽量留到最后处理。

## Codex：压缩结果要能接力

Codex 的压缩路径分两种。非 codex 模型走公开源码里的本地流程：CLI 把当前对话交给一个 LLM，要求它生成 handoff summary——写清当前进度、关键决策、用户约束、下一步，以及继续任务需要的数据。下一轮恢复时，CLI 在摘要前加一段 handoff prefix，告诉新模型：前一个模型已经做过一部分工作，这是它留下的接力摘要。codex 模型走服务端 `compact()`，拿到一个加密 blob，客户端看不到摘要明文。

对 Pico 的启示：**压缩关注的不是 token 变少，而是任务恢复。**压缩结果要能接续下一轮模型接着干活，里面需要留下目标、约束、进度、关键决策和下一步。

## OpenCode：先便宜地清，再重地摘要

OpenCode 的思想是先做便宜的清理，再做重的摘要。第一步 **Prune** 轻量、不调用 LLM：从最近消息往前扫，跳过最近 2 轮用户对话，保护最近约 40k token 的工具输出；更早的旧工具输出标记为 compacted，发给模型时替换成占位，原始数据还在 session 存储里。第二步 **Summary** 才调用 LLM：只在上下文接近上限时触发，把旧对话整理成固定结构的 handoff（Goal、Constraints & Preferences、Progress、Key Decisions、Next Steps、Critical Context、Relevant Files），同时保留最近 2 个 turn 作为工作现场。

对 Pico 的启示：**低价值高体积的内容先擦，任务状态压成结构化交接，同时保留最近现场。**这一条和 Pico 的 Curator 设计几乎是同一个思路。

# 三、Pico 的组装链路：四个阶段

Pico 在每次模型调用前跑一条组装链路。它只有一条实现：`ContextAssembler`，把六个 `SegmentBuilder` 按 `order` 注册，拆成两个阶段跑。第一阶段是预算，第二阶段是固定材料，第三阶段是历史选择，第四阶段是结构保真。前五个 Segment 是"固定材料"——它们每轮都进，只是内容随请求变化；只有第六个 Curator 决定"过去哪些信息进入本轮"。

## 阶段一：先做保守预算，不假装一开始就精确

`AgentLoop._make_token_budget()` 先构造一个 `TokenBudget`，把窗口拆成四块预留加一块剩余：

```text
context_length
reserved_output
reserved_tools
reserved_system
available_history
```

`available_history` 等于窗口减去输出、工具、系统三块预留：

```text
available_history
= context_length
- reserved_output
- reserved_tools
- reserved_system
```

这是**第一层估算**：`ContextBuilder.estimate_system_tokens()` 用一套代表性系统 Prompt 做预算。它此时还不知道当轮 Memory recall 命中多少内容、Skill Router 注入哪些技能、Curator 最后产生多长的 Working State。`available_history` 的作用是给组装流程一个保守边界，不是最终额度。

第二层校验在 Phase A 之后。Slow Path 或 Fallback 提交历史计划时，`CuratorAssembler.build()` 会让 `HistoryTrimmer.trim()` 用完整的一套材料重新估算：实际 system 前缀、可选的 Curator Working State、计划选中的 history、当前 user 消息、当轮 tools 定义、预留的输出 token。若仍超限，就按完整 Turn group 删除可删历史。这才是 Slow/Fallback 路径的最终预算约束。

## 阶段二：Phase A 并行收集五类固定材料

`build_context_engine()` 注册六个 Builder。前五个 `needs_prefix=False`，`ContextAssembler` 在 Phase A 用 `asyncio.gather()` 并行构建；Curator 是第六个，等前缀完成后串行运行。

| 顺序 | Segment | 材料来源 | 作用 |
|-|-|-|-|
| 1 | Identity | Workspace 与 Runtime 身份。 | 告诉模型它在 Pico 仓库中、以什么身份工作。 |
| 2 | Bootstrap | 项目启动文件与规则。 | 告诉模型测试命令、代码规范和项目约束。 |
| 3 | Memory | 本地 MemoryStore 与可选 `MemoryBackend.recall()`。 | 提供此前处理类似任务的经验（如果召回到）。 |
| 4 | Active Skills | 当前已激活技能。 | 告诉模型当前正在用哪些工作方法。 |
| 5 | Skills | SkillForgeRouter 从本地技能目录选出的候选。 | 按当前任务补充代码诊断或测试技能。 |
| 6 | Curator | Session manifest、archive、Working State。 | 决定哪些历史消息与工具交换进入当前轮。 |

五个 Builder 能并行的条件很干净：它们都只读同一份只读 `AssemblyContext`（session key、current message、media、channel、chat id、候选 Session 消息和预算），此时 `ctx.prefix` 还是 `None`，彼此不依赖结果。并行完成后，Assembler 仍按 Builder 的 `order` 排序拼接文本，系统 Prompt 的顺序不会随机——稳定前缀对 prompt cache 友好，也保证身份规则永远在技能之前。

Phase A 完成后，Assembler 做三件事：按顺序连接五个 Segment 的 `text` 得到实际 `system_prefix`；把当前文本和媒体构造成唯一的 `user_message`；从 Tool Registry 取出当轮 `tool_defs`。三者包进 `AssembledPrefix` 交给 Phase B——它代表"历史之外已经确定的输入开销"，Curator 可以围绕真实前缀选择历史，而不是只盯一个脱离本轮任务的固定数字。

Memory 在这里有一条必经路径：只有被召回、渲染进 Segment、最终进入 system 前缀，模型这一轮才能用。RAG 负责"从外部知识里找材料"，Context Engine 负责决定这些材料怎样和规则、历史、工具、当前请求一起进模型——这是两者的分界。被检索出来的文本仍然是数据，不会因为进了 Context 就变成可信指令；网页、用户文件、工具结果都可能夹带诱导模型改变行为的内容。Context Engine 负责组装与裁剪，不负责消除 Prompt Injection。

## 阶段三：Curator 决定过去哪些信息进入本轮

Curator 是 `order=6`、`needs_prefix=True` 的 SegmentBuilder，一次产生两类输出：`text`（可选的 `# Curator Working State`，进 system 第六段）和 `history`（本轮选中的 Session 消息，进 system 与 current user 之间）。

它先为 Session 历史建立 **manifest**——一张轻量目录，每条记录保留消息 id、role、token 估算、相关性、是否受保护和所属工具组。Curator 先读目录，只有需要时才搜索或取回更重的正文。**protected** 表示裁剪时不能随意删除的消息；**archive** 把低价值旧消息无损落盘，需要时按引用取回，不必让全部正文一直占着窗口。

Curator 根据历史 token 与可用历史预算的关系选择三条路径，这是整条链路的核心决策点：

### 路径一：Fast Path，历史短就完整直通

```text
history_tokens < available_history * fast_path_threshold
```

默认 `fast_path_threshold=0.60`。低于阈值时，Curator 不调用内部模型，也不运行 `HistoryTrimmer`，只把 Session 消息投影到 Provider 支持的字段集合后完整返回。**Fast 的速度来自少做一步**：阈值用第一层 `available_history`，这条路径不会再拿实际完整 Prompt 跑 Trimmer。读代码时把它理解成快速直通条件，它本身不是一次精确的全量预算校验。

### 路径二：Slow Path，让受限的内部 Curator 提交计划

历史达到阈值后，Curator 内部模型读取 manifest，可以搜索 Session、取回 archive、设置相关性、更新 Working State，最后通过工具提交 `ContextPlan`。步骤上限默认 12，整体超时默认 30 秒。模型交了计划也不作数，必须过确定性验证；有效计划进入 `CuratorAssembler.build()`，再由 `HistoryTrimmer` 闭合工具配对并检查完整 Prompt 预算。

Curator 的 system prompt 把边界写得非常死：它只负责构建下一个主 Agent 的上下文窗口，永不回答用户、永不编造消息内容、永不调用外部工具。它手上只有 7 个内部工具：查预算、归档、取回归档、搜索 manifest、设置相关性、更新 Working State、提交计划。它没有主 Agent 的任意文件/shell 能力——这是一个被刻意阉割的模型。

### 路径三：Fallback，内部选择失败时的确定性计划

内部模型超时、Provider 报错、没有完成工具提交、计划非法或步骤耗尽，Curator 就生成一份确定性计划：合并受保护消息、相关性排名靠前的消息、最近消息三类 id。计划同样进入 `CuratorAssembler.build() → HistoryTrimmer.trim()`，元数据记录 `path="fallback"` 和具体 `fallback_reason`。半成品历史不会交给主 Agent。

![](images/P04/img2.jpg)

Fallback 只兜 Curator 内部的历史选择失败。Memory recall 的连接或认证错误、其他 Phase A Builder 的异常不会被吞掉；这些错误会让 Context 组装失败，继续向 Agent Loop 传播。

## 阶段四：HistoryTrimmer 按结构裁剪，不按字符串截断

这是整条链路里最硬的一层。模型与工具之间存在结构契约：

```text
assistant(tool_calls=[{"id": "call_7", ...}])
tool(tool_call_id="call_7", content="pytest failed ...")
```

只保留第二条，Provider 会看到一个没有父调用的 Tool Result；只保留第一条，会看到一个没有结果的 Tool Call。两种情况都可能破坏协议。

**第一步，`canonical_ids()` 做工具配对闭合。**接受计划选中的消息 id：选中 assistant Tool Call 就补入相同 `tool_call_id` 的 Tool Result；选中 Tool Result 就反向补入父 assistant 消息。补齐循环进行，直到选中集合不再变化。最后丢弃开头位于首个 user 消息之前的残片，避免历史从一段工具交换中间开始。

**第二步，`history_from_ids()` 只投影 Provider 支持的字段。**Session 消息可能带时间戳、内部索引或 manifest 注释，这些是 Runtime 自己的状态，不该未经处理发给 Provider。白名单只有 7 个键：role、content、tool_calls、tool_call_id、name、reasoning_content、thinking_blocks——reasoning 字段必须存活，多轮推理契约（如 DeepSeek thinking mode）靠它延续。

**第三步，用完整 Prompt 估算，不只数 history。**`trim()` 通过调用方提供的 `build_messages(history)` 构造 system + history + current user，把 tools 一起交给 token 估算链：

```text
max_prompt_tokens = context_window_tokens - reserved_output
```

**第四步，超限时删除完整 Turn group。**Trimmer 以 user 消息为边界，把历史分成完整 Turn group；排除含 protected 消息的组，按相关性与位置挑一个低优先级组整体删除，再重新做闭合与 token 估算。裁剪单位是整个 Turn，不是单条消息——单条删会拆散工具配对，也会留下没有问题的残缺对话。

**第五步，不能再删时，明确报告超限。**剩余组都受保护时，Trimmer 不会为了假装成功而破坏结构。`TrimOutcome.ok` 会是 false，`over_by` 给出还超出多少 token，warnings 记录删除过哪些 Turn。

## 合成层：四个槽位合成一次 Provider 调用

Phase B 返回后，`ContextAssembler` 汇总所有 Segment：Phase A 的文本按 order 构成固定 system 前缀；Curator Working State 若存在，作为第六段加入 system；Curator 选中的 history 放在 system 与当前 user 之间；当前 user 保持唯一且位于最后；tools 仍由 Agent Loop 作为独立参数交给 Provider。

所有 Segment 的 `meta` 合并进 `AssembledContext.metadata`——memory hits、注入的 skill ids、Curator path、fallback reason、validation、include indices 等诊断信息都在这里。四个对象的职责边界：Session 保存完整记录但只提供候选；Context Engine 只拥有本轮的组装结果；Memory / Archive 保存可再次取回的外部状态；Provider 只看到最终请求。

# 四、关键 trade-off：每个参数为什么是这个值

## 为什么 fast_path_threshold 是 0.60，不是 1.0

Fast Path 不经过 HistoryTrimmer，不做完整 Prompt 校验。阈值越高，越多轮次走这条"少做一步"的路；但如果历史已经占了 80% 预算还直通，前缀一旦波动就可能超限。0.60 意味着：只有历史占用明显低于预算时才相信第一层估算。这是用"偶尔多走 Slow Path"换"Fast 不会把预算算爆"。

## 为什么 Curator 是 12 步 / 30 秒，还内置 7 个工具

Slow Path 是整条链路唯一调用内部模型的环节，它必须有界，否则一次上下文组装会拖垮整个 Turn。12 步封顶防止内部模型空转；30 秒超时兜住 Provider 慢响应；7 个工具全是只读或确定性操作（查预算、归档、取回、搜索、标相关性、写工作状态、交计划），内部模型没有任何写外部世界的通道。每一步的取舍都是同一个原则：**内部模型只负责"选哪些消息"，不负责"决定系统行为"。**

## 为什么保护最近 turn，以及 protected 的规则

最近的消息相关性被抬到 0.75 以上，开头的 `protect_first_n * 2` 条消息被标记为 protected——保护的是"用户说了什么 → 我做了什么 → 结果是什么"这个完整一跳。裁剪时排除含 protected 消息的组，宁可报告超限也不破坏这条链。这和 Codex 的 handoff、OpenCode 的"保留最近 2 个 turn"是同一个直觉：最近的上下文承载当前任务，旧的上下文可以被压。

## 为什么 Fast 不过 Trimmer，Slow/Fallback 必须过

Fast 是"历史短、第一层估算足够可信"的快速直通条件；Slow 和 Fallback 提交的是经过筛选的计划，必须由 HistoryTrimmer 做三件事：闭合工具配对、投影 provider-safe 字段、用完整 Prompt 校验预算。这是确定性对非确定性的最后一道闸：**内部模型可以提建议，但结构完整性由确定性代码保证。**

## 为什么 Memory 失败不能伪装成 Curator Fallback

有 Fallback 不等于任何错误都能继续运行。可靠系统先明确哪个组件拥有恢复所需的事实，再决定它能不能降级。Curator 拥有确定性历史选择规则，所以能保底；Memory 认证失败没有可信替代事实，就只能失败。把基础设施故障伪装成"没有记忆"，比失败更危险。

# 参考

- [simzhou｜How Codex compacts context](https://simzhou.com/en/posts/2026/how-codex-compacts-context/)：Codex 服务端 compact 路径的探测实验。
- [justin3go｜Context compaction in Codex, Claude Code and OpenCode](https://justin3go.com/posts/2026/04/09-context-compaction-in-codex-claude-code-and-opencode)：三个 Harness 压缩策略的对比。
- [Anthropic｜Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)：Context Engineering 的总体定义。
- [Lost in the Middle](https://arxiv.org/abs/2307.03172)：长上下文里信息位置如何影响模型使用效果。
- [RULER](https://arxiv.org/abs/2404.06654)：标称窗口长度与复杂长上下文任务表现之间的差距。
- [ReAct](https://arxiv.org/abs/2210.03629)：Agent 为什么在推理、动作、观察之间循环，持续制造新历史。
- [Anthropic｜Prompt injection defenses](https://www.anthropic.com/research/prompt-injection-defenses)：工具结果和外部内容进入 Context 后的不可信输入边界。