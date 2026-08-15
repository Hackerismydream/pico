# GPT Pro Prompt：P07 Tools 与执行治理

## 角色与目标

你是 Pico 技术教程的作者，负责重写 P07。

这不是对旧 P07 的局部润色，也不是按照源码目录逐个介绍模块。你要从开发 Agent Harness 的视角，讲清一个独立的工程领域：Tool System / Action Runtime，也就是模型意图如何经过契约、治理和执行边界，变成一次受控、可观察、可以正确收束的现实行动。

读者最终应该能够回答：

> 模型输出了一段工具调用 JSON，为什么 Harness 不能直接执行它？在它获得读取文件、修改代码、启动进程或访问远端服务的资格之前，系统还必须完成哪些设计？

建议标题：

`P07｜Tools 与执行治理：模型意图如何变成受控行动`

可以调整副标题，但不能把本章写成 Tool API 使用教程、Pico 文件索引或 MCP 协议教程。

## 远程材料与事实来源

你只能依赖 GitHub 上可以访问的仓库和公开资料，不要假设可以访问作者本机、飞书文档或本机安装目录。

### Pico 主仓库

- 仓库：https://github.com/Hackerismydream/pico
- 默认事实基线：最新 `main`
- 术语入口：`CONTEXT-MAP.md`、`CONTEXT.md`、`ui-tui/CONTEXT.md`
- 架构文档：`docs/architecture/`

写作前先确认 GitHub `main` 的最新提交。源码、测试、术语表与历史文章冲突时，以当前 `main` 的源码和测试为准。不要为了写文章修改代码，也不要在正文中堆砌 commit SHA。

### 当前 P05 写作参考

在 Pico 仓库阅读：

`feishu/chapters/P05-P05｜Session 与恢复.md`

GitHub 直达链接：

https://github.com/Hackerismydream/pico/blob/main/feishu/chapters/P05-P05%EF%BD%9CSession%20%E4%B8%8E%E6%81%A2%E5%A4%8D.md

该文件是飞书 revision 361 的文本快照，仍在人工修改。至少精读开头和前三节，再浏览全文。

需要学习的是它的论证方式：

- 先界定一个 Harness 领域拥有和不拥有的责任；
- 用一个看起来合理的朴素方案暴露真正困难；
- 比较行业实现时，从同一组问题出发推导设计空间，而不是罗列功能；
- 明确区分当前实现、设计推论和未来 proposal；
- 让源码服务于工程问题，不让文件结构决定文章结构。

不要复制 P05 的标题格式、小节数量、粗体节奏、图形布局和句式。P05 仍是未完成稿，其中不自然的过渡、残缺表达、重复判断和过量 callout 也不要照搬。P05 中的第三方实现描述只能作为写作样式参考，P07 的技术事实仍需重新核验。

### 旧 P07 历史稿

在 Pico 仓库阅读：

`feishu/chapters/P07-P07｜Tools 与执行边界：从一次测试命令走到 MCP 和 Subagent.md`

GitHub 直达链接：

https://github.com/Hackerismydream/pico/blob/main/feishu/chapters/P07-P07%EF%BD%9CTools%20%E4%B8%8E%E6%89%A7%E8%A1%8C%E8%BE%B9%E7%95%8C%EF%BC%9A%E4%BB%8E%E4%B8%80%E6%AC%A1%E6%B5%8B%E8%AF%95%E5%91%BD%E4%BB%A4%E8%B5%B0%E5%88%B0%20MCP%20%E5%92%8C%20Subagent.md

旧稿只用于了解历史内容和发现需要淘汰的结构，不能作为当前实现证据。旧稿把 Agent Loop、Registry、Sandbox、Trust、MCP、tool_search 和 Subagent 串成模块游览，领域过宽；其中关于工具调用顺序、当前能力和源码路径的描述也可能已经过时。

## 先做范围判断，再直接写完整初稿

正式正文前先输出一段不超过 600 个汉字的“范围判断”，回答：

1. P07 对应 Agent Harness 的哪个设计领域？
2. Tool、MCP、Sandbox、权限、并发、取消和结果回注是什么关系？
3. 哪些问题必须进入 P07？
4. 哪些内容虽然在代码中相邻，却属于其他章节？
5. 为什么 Subagent 不应继续占据本章主线？

完成范围判断后不要等待确认，继续输出完整初稿。

## 本章的第一性原理问题

整章围绕这个问题推进：

> 模型给出的只是一个带参数的行动建议，它凭什么获得改变真实世界的资格？

需要自然建立这条因果链：

```text
模型看到能力
→ 模型生成调用意图
→ Harness 识别调用身份与来源
→ 参数被校验和归一化
→ 系统判断副作用与执行边界
→ 调度器决定顺序、并发和屏障
→ 执行器占用文件、进程或远端服务
→ 超时、失败和取消得到收束
→ 结果与执行证据被送回模型
```

源码、行业比较和实验都要回答这条链上的问题。

## Tool System 的完整性问题

下面是研究与自检问题，不是强制目录。请按照文章自身的因果关系重新组织，不要让每一项机械对应一个小节。

### 能力描述与披露

- Tool schema 为什么是模型可见的能力合同，而不只是 Python 函数签名？
- 名称、描述、参数 schema 和返回语义怎样影响模型选择？
- Tool Registry 为什么不只是一个字典？
- 工具数量变大后，为什么不能无条件把全部 schema 放进每次 Provider 调用？
- `tool_search` 与 `tool_call` 解决了什么，又引入了哪些身份和观测问题？

这里只解释 Tool 能力如何进入模型可见范围，不要重写 P04 的 Context Compaction。

### 调用身份与来源

核对并解释 Tool Invocation、Tool Execution Context、call ID，以及 progressive `tool_call` 的 parent identity 与 target identity。

不要写成字段说明。用故障场景解释：如果事件只知道外层 `tool_call`，不知道真正执行的是哪个目标工具，审计、耗时统计和故障定位会丢失什么？

### 参数验证与失败语义

- 为什么模型输出不能直接作为可信函数参数？
- JSON Schema 校验、类型转换和默认值分别解决什么？
- 为什么“工具返回失败”与“Agent Loop 崩溃”不能是同一种终态？
- 哪些错误应形成可恢复的 ToolResult，哪些异常必须向上终止？
- 为什么一个普通字符串不足以表达成功、失败和结构化证据？

### 副作用分类与调度

这是 current Pico 相比旧 P07 必须新增的重点。核对 current `main` 中的 Tool Capability、Tool Effect、`concurrency_safe`、有界并发、串行屏障、结果顺序和 sibling cancellation。

需要解释两个都不正确的极端：

- 所有工具永远串行，能够避免部分竞态，却浪费独立只读操作之间的等待时间；
- 只要函数是 async 就全部并行，可能让写入、命令执行和外部副作用发生竞态。

不要把 `concurrency_safe=true` 单独视为并行许可。必须从 current `main` 核实 effect 与 concurrency safety 的组合规则、默认最大并行度，以及写入、执行、外部调用和未知效果是否形成屏障。

### 现实资源的执行边界

区分普通进程内 Tool、文件系统 Tool、Shell Tool、Sandbox executor 与远端 MCP Tool。

Sandbox 是工具执行的一种资源边界，不是 Tool System 的同义词。不是所有 Tool 都自动进入 Sandbox，也不能把当前实现写成已经拥有统一、完整的审批系统。

可以讨论 permission 和 approval 为什么是 Harness 必须面对的问题。如果 current Pico 没有完整生产接线，只能把它写成边界、缺口或外部 Host 的责任，不能写成已实现能力。

### 超时、取消与资源清理

- timeout 为什么只表示调用方不再等待，不能自动证明底层资源已经停止？
- 并发批次中一个调用失败后，其他 sibling task 应怎样处理？
- 子进程在取消后为什么需要显式终止并等待退出？
- 返回失败、抛出异常和取消整个 Turn 分别意味着什么？
- cleanup 为什么属于 Tool System 的正确性，而不只是实现细节？

从现实资源出发解释，不要只介绍 `asyncio` API。

### 结果信任与执行证据

- 工具返回内容为什么仍然是不可信输入？
- exit code、stdout、stderr、结构化 ToolResult 和模型看到的文本是什么关系？
- ToolEvent 应记录哪些身份、效果、耗时和终态证据？
- 观察到一次调用与证明现实副作用已经成功，为什么不是一回事？

这里只讲 Tool 层必须交出的执行证据，不展开 P10 的完整 Tracing 架构。

### 扩展与生命周期

用 MCP 检验 Tool Contract 是否足够通用：

- 本地 Python Tool 与远端 MCP Tool 怎样进入统一 Registry？
- MCP schema、调用、连接和关闭生命周期分别由谁负责？
- duplicate registration 为什么不能静默覆盖？
- transport failure 与 tool-level failure 如何区分？

MCP 是重要扩展案例，但不要让文章变成 MCP 协议教程。

## 贯穿全文的真实任务

用一条代码维护任务贯穿全文，例如：

> 在仓库中定位工具超时配置，读取相关实现，修改一个文件，并运行对应测试。

这条请求自然产生搜索、多文件读取、文件修改和测试命令执行。用它解释：

- 哪些读取能够组成安全并行组；
- 为什么写入构成屏障；
- 为什么测试命令不能与写入任意重叠；
- Tool Result 怎样进入下一次模型调用；
- 取消发生时哪些任务和子进程必须被清理。

开篇先让本地 happy path 闭合，再扩展到 MCP、失败与取消。不要同时塞入 Web、MCP、Subagent 和多种异常。

## 行业方案的远程来源

至少研究三套真实实现。每个第三方机制必须有直接源码或官方文档证据，不得从模型记忆补齐。

### Pi

- 公开仓库：https://github.com/earendil-works/pi
- 重点目录：`packages/coding-agent/`、`packages/agent/`、相关 Tool 与 extension 文档

### Claude Code

- 可读研究材料：https://github.com/QUSETIONS/MiniCode-Python
- 优先检查其中 `claude-code-src/` 的实际结构
- 该仓库属于研究或反编译材料，只能用于定位实现线索，不代表 Anthropic 官方公开承诺
- 对重要结论再寻找 Anthropic 官方文档进行交叉验证；无法验证的机制删掉

### Codex

- 官方源码：https://github.com/openai/codex
- 优先阅读 `codex-rs/` 中与 tools、sandbox、approval、exec、MCP 和 turn execution 直接相关的实现与测试

### OpenCode

- 官方源码：https://github.com/anomalyco/opencode
- 优先阅读 `packages/opencode/` 中与 tool、permission、shell、MCP 和 session message part 相关的实现与测试

不要按照“产品 A 有什么、产品 B 有什么”逐个介绍。围绕相同问题横向比较：

- Tool contract 如何定义；
- 能力怎样披露；
- permission 与用户确认放在哪里；
- 命令在哪种资源边界执行；
- 多个调用怎样排序或并行；
- timeout 与 cancellation 怎样收束；
- Tool result 怎样回到模型；
- MCP 或插件怎样扩展能力。

比较的目的，是从实现差异中推导 Tool System 的设计坐标，再把 Pico 放入坐标系。无需为了凑齐四套产品而写无法验证的内容，三套证据完整的比较优于四套依赖猜测的介绍。

## Pico 源码锚点

至少核对以下 current `main` 路径，不要求在正文中逐个罗列：

- `pico/agent/tools/base.py`
- `pico/agent/tools/execution.py`
- `pico/agent/tools/registry.py`
- `pico/agent/tools/tool_search.py`
- `pico/agent/tools/mcp.py`
- `pico/agent/tools/filesystem.py`
- `pico/agent/tools/file_search.py`
- `pico/agent/tools/shell.py`
- `pico/agent/tools/web.py`
- `pico/agent/loop/main.py`
- `pico/sandbox/interfaces.py`
- `pico/sandbox/direct_executor.py`
- `pico/sandbox/boxlite_executor.py`

至少核对相关测试：

- `tests/test_tool_registry_execution.py`
- `tests/test_tool_registry_timeout.py`
- `tests/test_agent_loop_tool_search.py`
- `tests/test_tool_search.py`
- `tests/test_mcp_tools.py`
- `tests/test_sandbox_unit.py`
- `tests/test_sandbox_integration.py`
- `tests/test_agent_loop_run_emit.py`
- `tests/test_picobench_tool_execution_experiments.py`
- `tests/integration/test_picobench_mcp_e2e.py`

如果路径在 current `main` 已变化，找到当前对应实现并更新引用，不要把不存在的旧路径写进正文。

## 必须重新核实的当前事实

下面是核验问题，不是可以直接复制的结论：

- Tool Execution Context 是否不可变，怎样传播调用身份和来源？
- Tool Capability 怎样描述 effect 与 concurrency safety？
- 哪些条件同时成立时调用才允许并行？
- 默认最大并行度是多少，在哪里配置？
- 返回结果是否维持模型调用的原始顺序？
- 批次失败、回调异常或取消时 sibling task 怎样退出？
- grep 或其他子进程怎样在取消时清理？
- progressive `tool_call` 怎样保存 parent call ID 和 target tool identity？
- ToolEvent 最终能否看到实际目标工具？
- duplicate registration 是否需要显式 replacement？
- MCP 连接、调用与关闭由谁拥有？

任何一项如果与这里的暗示不同，以 current `main` 为准。

## 证据边界

如果 Pico 仓库仍保留 scheduler microbenchmark，可以作为机制验证，但必须说明它是 synthetic async scheduler microbenchmark。它不能证明真实文件系统、网络调用或完整 Agent 任务获得相同比例的加速。如果产物标记 `positive_claim_eligible=false`，不得写成正向产品性能结论。

如果引用渐进式 Tool 披露实验，必须同时写出 token 与任务质量结果，并核对当前仓库里的精确数字。历史结果曾出现可见 schema token 大幅下降、同时任务通过数下降的情况，因此不能只摘 token 降幅，删除质量退化后宣称综合优化成功。

## 相邻章节边界

本章可以触碰接缝，但不能吞并这些领域：

- Agent Loop 与 Turn 生命周期属于 P03；
- Tool schema 占用 Context 属于 P04；
- Session 与恢复属于 P05；
- Memory 与 Skill 属于 P06；
- Gateway 与 Delivery 属于 P08；
- Provider token 与缓存核算属于 P09；
- 完整 Tracing 属于 P10；
- 综合 Evaluation 属于 P11；
- Evolver 属于 P12。

Subagent 不作为本章主线。可以在边界处说明：

> spawn 可以用 Tool 形式暴露给模型，但它启动的是另一个受调度的 Agent 执行单元。Tool System 负责入口合同，Subagent 系统负责后续生命周期。

随后停止，不展开 Subagent 的配额、独立 Agent Loop、后台生命周期和结果归并。

## 配图要求

不要生成图片，不要画 Mermaid，也不要创建 SVG、PNG 或其他图片文件。

正文中只安排 2 至 4 个真正需要图解的位置，并在文末为每张图提供可以交给图像生成 Agent 的中文绘图 Prompt。每份绘图 Prompt 必须包含：

- 图号与图题；
- 这张图要回答的工程问题；
- 画面结构、节点、箭头和分区；
- 必须出现的规范术语；
- 不得出现的误导关系；
- 建议的宽高比、视觉层级和配色职责；
- 正文中的插入位置、图前引导句和图后结论。

优先考虑以下图的叙事职责，但不要机械照搬：

1. 模型意图变成受控行动的完整链路；
2. READ 并行组与 WRITE、EXECUTE、EXTERNAL 屏障构成的效果感知调度时间线；
3. 本地 Tool、Sandbox 与 MCP 的资源和信任边界。

图稿 Prompt 要描述技术关系，不指定某个本机绘图工具或 Skill 名称。

## 写作要求

- 标题格式为 `P07｜主题名`。
- 开头直接进入模型准备调用工具的具体时刻，不写“读前准备”“学习目标”。
- 先建立问题和可见结果，再出现大段 Pico 文件名。
- 术语首次出现使用“中文（English）”，后文使用规范中文。
- 术语与 `CONTEXT.md` 一致，不自创同义词。
- 用自然中文解释工程问题，允许短句落判断，但不要每段都收束成金句。
- 不排比，不对仗，不使用工整三连。
- 不复制 P05 的节数、标题结构和 callout 节奏。
- 全章加粗判断句不超过 5 处。
- 比喻最多 1 至 2 个，只在确实降低理解门槛时使用。
- 数字、函数名、参数名、文件路径都从 current `main` 或 commit-bound 实验产物核实。
- 当前实现、历史实现、行业实现、设计建议和未来 proposal 必须明确区分。
- 文末参考资料中的链接必须可以从远程访问，并说明每项资料支持什么结论。

禁用：

- 破折号字符“——”；
- “首先、其次、最后”；
- “值得注意的是”；
- “综上所述”；
- “本质上”；
- “下面我们来”；
- “这一节要回答”；
- “通过以上分析可以看出”；
- 编造函数、参数、性能数字、产品行为或个人经历。

## 交付格式

按以下顺序一次性交付：

1. 范围判断，不超过 600 个汉字；
2. P07 完整 Markdown 初稿；
3. 配图位置与 2 至 4 份完整中文绘图 Prompt，不生成图片；
4. 参考资料；
5. 事实核验表，包含关键事实、对应源码或测试、当前实现或 proposal、证据强度；
6. 与 P05、P06 的结构差异说明，不超过 500 个汉字。

交付前检查：

- 抽出任意三段，如果可以无痕换到 P05 或 P06，说明 Tool 领域特征不够强，需要重写；
- 删除文件名后，如果文章无法讲清 Tool System 的设计问题，说明它仍是模块导览；
- 删除产品名称后，如果行业比较没有留下可复用的设计坐标，说明它仍是功能罗列；
- 如果把 Subagent、Sandbox、MCP 和 Tracing 写成四个并列系统，说明领域边界失控，需要重新收紧；
- 如果存在本机绝对路径、飞书依赖或 GPT Pro 无法访问的材料，必须改成公开 GitHub 链接或删掉。
