# P06A｜Memory

<!-- Feishu source revision: 77; exported: 2026-08-16. Image binaries are intentionally not tracked. -->

设想用户在一次代码审查里纠正 Agent：这个仓库的发布说明只能写已经被测试、源码或运行工件证明的结论。几次 Session 之后，他又在同一个仓库里让 Agent 更新文档。系统若完全忘记，用户必须再次解释；系统若把上次对话里的所有内容都当成 Memory，它又可能把当时的测试结果、已经废弃的命令和模型自己的猜测一起带回来。一个没有长期记忆（Memory）的 Agent 会重复探索，一个没有边界的 Memory 会把旧错误变成稳定习惯。

会话（Session）可以保存当时说过什么，上下文（Context）可以决定这一轮让模型看见什么，Memory 处理的却是另一个问题：过去发生的哪些事情，仍然有资格改变未来的默认行为。可以把 Session 想成采访录音，Memory 像编辑部整理出的资料卡，当前源码、文档和外部系统则是发稿前的事实核验。录音适合完整保留，资料卡应当少而清楚；资料卡即使曾经正确，也不能越过今天的事实源直接定稿。

Memory 的质量不由保存量决定。更关键的指标，是错误记忆进入未来决策的概率。

于是，学习 Agent Memory 的入口应当放在存储之前：一段经历是否具有长期复用价值，保存原话还是抽象结论，它属于用户、仓库还是一次任务，事实何时会过期，冲突怎样替换旧结论，召回不到与存储故障为何必须区分，模型最终看到的文字又能否回到原始证据。

仍以开头那条纠正为例。用户要求“发布结论必须有源码、测试或运行工件支撑”。下一次写文档时，系统需要把这条要求带回来，同时避免把上次测试的数字当成永远有效的事实。图 P06A-1 要回答的问题是：一句有用的纠正，经过哪些关口才有资格影响下一次任务？阅读时先沿上半部分看它怎样从经历变成记录，再沿下半部分看它怎样从记录进入当前 Context。

![图 P06A-1｜一段经历成为可用 Memory 之前要经过写入与读取两次审查](../images/P06A/P06A-1.png)

图中左半部分决定“什么可以留下”，右半部分决定“什么此刻可以使用”。候选提取、持久化和召回只是中间动作，真正承载可靠性的，是写入许可（write admission）、作用域、来源追踪（provenance）、更新时间、召回许可（recall admission）与当前事实核验。任意一层缺失，系统都可能成功检索到一条不该相信的内容。这里先得到本章的第一条工程判断：检索位于 Memory 管线中段，可靠性来自它前后的编辑与核验。

## 记忆的第一道门，不是检索

大模型没有跨请求延续的隐藏脑区。一次模型提供商（Provider）调用结束后，下一次调用能够使用的只有重新送入 Context 的内容，以及模型参数中原本就存在的知识。Agent 所说的“记住”，是运行时把某种状态写到模型之外，未来再选择性地读回来。工程上的 Memory 由外部状态管理和 Context 注入共同构成。

认知架构（cognitive architecture）常把记忆分为工作记忆、情景记忆、语义记忆和程序记忆。这个分类描述用途，与文件格式相互独立。一个 Markdown 文件可以混着写四类内容；向量库保存 embedding，只说明它具备一种索引方式。

| 类型 | 它回答的问题 | Coding Agent 中的例子 | 更合适的载体 | 主要失效方式 |
|-|-|-|-|-|
| 工作记忆（working memory） | 当前正在做什么 | 本轮计划、刚读过的文件、待验证假设 | 当前 Context、工作状态（Working State） | 窗口溢出、轮次结束 |
| 情景记忆（episodic memory） | 某次经历发生了什么 | 某次迁移为何失败、用户当时否决了哪种方案 | 带时间与来源的事件记录 | 事件被误当作长期事实 |
| 语义记忆（semantic memory） | 现在较稳定地成立什么 | 用户偏好、仓库约定、长期架构决策 | 可更新的资料卡、规则文件、索引 | 过期、作用域泄漏、冲突未替换 |
| 程序记忆（procedural memory） | 遇到这类任务怎样做 | 发布检查步骤、故障排查顺序、验收脚本 | 技能（Skill）、规则、可执行脚本 | 流程变更、步骤未经验证 |

这张分类表只回答“记忆用来做什么”。要判断一条记录能否进入未来决策，还要补三条坐标：

| 坐标 | 它解决的问题 | 同一句话可能出现的差异 |
|-|-|-|
| 作用域（scope） | 它对谁、哪个仓库、哪类任务有效 | “测试必须用 uv”可能是个人习惯，也可能只属于 Pico 仓库 |
| 证据状态（epistemic status） | 它是用户明确要求、工具观察，还是模型推断 | 用户说“必须”与助手总结“似乎更合适”不能拥有同一权重 |
| 时间状态（temporal status） | 它仍然 active，已经 superseded，还是尚未核验 | 上个版本的命令可以保留为历史，但不能继续充当当前默认值 |

类型、作用域、证据状态和时间状态解决的是四个不同问题。把一条记录标成“语义记忆”，并没有说明它属于哪个项目、依据什么成立、今天是否仍然有效。Memory 系统若只做内容分类，仍会在最关键的决策点上猜测。

这里最容易出现两个混淆。Context 中的计划属于当轮工作记忆，轮次结束后不会自行跨会话延续。能够被人审阅、版本控制和测试的复用流程，通常应进入技能（Skill）或项目规则；自动抽取适合处理仍需从经历中归纳的知识。

Session 记录发生过什么；Memory 从这些经历中维护未来仍值得依赖的部分。

Session 与 Memory 因而需要不同的取舍。Session 希望顺序完整、事实不丢，哪怕其中含有失败尝试；Memory 希望信号密度高、可更新、可拒绝，宁可遗漏一条低价值经验，也不应把一次偶然结果写成永久规则。检索增强生成（Retrieval-Augmented Generation，RAG）和 Memory 可以共用索引、召回与重排技术，但 RAG 面向一个外部知识库，Memory 还必须处理“这条知识由谁的哪次经历产生、是否仍有效、能否被用户更正或删除”。

向量检索只解决相似度。它不会自动回答权限、时间、真伪和作用域，也不会知道一条旧命令已经被仓库的新文档替换。把 Memory 简化成 `embed → top-k → 提示词（Prompt）`，等于把最危险的决策全部藏在相似度分数后面。

## 一段经历怎样被改写成未来能用的东西

假设用户说：“写 Pico 教程时，函数名和参数必须与当前源码一致，没量过的数字不要写。”原始消息当然可以留在 Session 里，但进入 Memory 时至少存在三种可能解释：这是一条适用于所有交流的全局偏好；这是一条只适用于 Pico 教程的项目规则；这只是当前交付的临时要求。三者文字相近，未来行为却完全不同。正确的 Memory 不能只保存句子，还要保存它的适用范围和证据强度。

一种便于推理的逻辑记录可以写成：

```text
claim       函数名与参数必须依据当前 Pico 源码核验，未测量数字不得写成事实
scope       repository=pico, task=tutorial-writing
source      用户显式要求，指向原 Session 与消息位置
observed_at 这条要求被确认的时间
status      active，可被更新或撤销
```

这是一份用于学习的最小语义，并非 Pico 当前 `Memory` 对象的数据模式。具体 Backend 可以用 Markdown、关系表、图结构或向量索引保存；缺少这些语义时，存储技术越强，错误传播也会越快。

一条经历从发生到真正影响未来行为，至少会经历六次状态变化：

```text
原始证据
  → 候选解释
  → 获准写入的记录
  → 归并后的当前状态
  → 本轮召回候选
  → 经当前事实核验后的行动依据
```

每个箭头都可能拒绝继续，也有不同的失败含义。提取失败表示系统没有形成候选；写入拒绝表示候选缺少长期价值或可靠作用域；归并失败意味着历史事件仍在，但当前资料尚未更新；空召回表示本轮没有合适记录；事实核验失败则要求 Agent 回到源码、配置或外部系统。把这些状态都压成一个 `memory_hit=true`，会丢掉修复问题所需的信息。

仍以教程发布口径为例。第一次纠正发生时，系统可以保存“用户要求所有结论都有证据”及其来源。假设后来仓库更换测试入口，新的工具结果和用户确认应把旧命令标成已被替代，同时保留旧记录解释变化过程。下一次召回时，长期要求仍可直接帮助规划；具体测试命令变化快，Agent 只把旧记录当成查找线索，并重新读取当前仓库。这里同时发生了稳定偏好的复用和漂移事实的核验。

### 候选通过许可后才成为记忆

一次轮次（Turn）里可能出现用户陈述、助手推断、工具输出和外部网页，它们的证据等级不同。用户消息最适合证明偏好和约束，工具与测试结果更适合证明仓库事实，助手总结只能说明模型怎样理解了现场，不能自动升级为事实源。若记忆写入器（Memory Writer）主要从助手的自我总结里抽取结论，模型产生的一次误解会在下一轮以“历史知识”的身份重新出现。

工具输出也不能无条件进入 Memory。网页、日志和仓库文件可能包含提示注入，测试结果可能只对当时的提交成立，Shell 输出还可能带凭据。写入前需要把它们视为数据，做来源标记、秘密清理与稳定性判断。Codex 当前的 Memory Writer 明确要求原始 rollout 不可修改、第三方内容只作为数据、秘密必须脱敏，并允许在没有高价值信号时返回空结果，这个空操作（no-op）出口比复杂的摘要模板更重要。

### 允许不写，是一个能力

很多 Memory 系统只评估“能不能抽取出一条”，却没有为空写入设计出口。一次临时构建失败、某个网页当前价格、模型未经验证的建议，都可能对眼前任务有用，但不值得改变以后每一轮的默认行为。写入许可要判断这条信息能否让未来 Agent 少犯错、少打扰用户，以及收益能否抵消过期与误导成本。

写入错误的影响会跨越许多未来轮次，因此写入端需要比普通检索更严格的许可。

低置信度候选可以留在情景记录里，不必提升为语义结论；缺少作用域的候选可以等待更多证据；与当前权威文档冲突的候选应当拒绝或标记为已被替代。空写入、空召回和拒绝回答（abstention）表示系统识别出证据不足，是完整合同中的成功结果。

### 归并维护当前状态

长期运行后，同一主题会出现许多事件：用户提出要求、Agent 第一次违反、用户纠正、项目规范更新。若系统把它们逐条追加到一份“长期事实”里，未来 Context 会同时出现互相冲突的版本。归并（consolidation）从事件中维护当前状态，同时保留来源和演化关系。

对项目状态来说，“当前使用 uv 运行测试”应当替换旧命令，旧记录保留为历史证据；对用户偏好来说，一次偶然选择不足以形成长期习惯，多次明确纠正才可能提升置信度；对程序知识来说，步骤只有经过实际验证，才有资格从“建议”提升为“复用流程”。更新、合并、废弃与删除必须是一等操作，否则 Memory 只能增长，不能变得更正确。

### 召回以后仍要核验

检索命中表示“这条记录和当前查询相近”，不表示“它现在仍然正确”。仓库中的测试命令、API 参数、负责人和版本状态都可能漂移。安全的读取路径应当根据变化概率与核验成本决定动作：低变化且核验昂贵的偏好可以直接使用；高变化且容易核验的命令应当先看当前文档或源码；高变化又难核验的结论可以作为线索，但最终回复需要说明它来自旧 Memory，当前状态尚未确认。

召回结果先作为候选证据进入任务，当前事实仍由当前事实源确认。

这个区别也解释了为什么 Memory 需要来源指针。没有来源的“用户喜欢简洁回复”还能勉强人工判断，没有 provenance 的“部署脚本必须带 `--legacy`”则很危险，因为无法知道它来自哪次失败、哪个分支、哪一版仓库，也无法在源码变化后定位该更新谁。

### 写入许可与召回许可控制不同风险

图 P06A-1 中有两道许可，它们不能合成一次相似度判断。写入许可面向未来，要估计一段经历是否值得反复影响后续任务；召回许可面向当前请求，要判断已经存在的记录此刻是否相关、是否越过作用域、是否已经过期。

| 决策点 | 错放一条的代价 | 少放一条的代价 | 更保守时会发生什么 |
|-|-|-|-|
| 写入许可 | 错误会在多个未来 Session 中反复出现 | Agent 以后多做一次探索或再次询问 | Memory 增长较慢，但污染面更小 |
| 召回许可 | 当前 Context 被旧事实或跨项目内容干扰 | 本轮需要回到源码重新查找 | 成本增加，但任务仍可从当前事实源完成 |

这是一种不对称风险。漏掉一条有用记忆，通常带来重复探索；写入一条错误记忆，可能改变许多未来任务的默认行为。召回端同样可以选择空结果，因为“重新查一次”常常比“自信地使用错误历史”更便宜。具体产品可以根据任务成本调整门槛，但应把这个取舍写成政策，而不是让 top-k 隐式决定。

## 四个 Coding Agent 把编辑权放在不同位置

Pi、Claude Code、Codex 与 OpenCode 都能让知识跨 Session 延续，但它们没有采用同一种 Memory。更有解释力的比较方式，是看“谁负责把经历编辑成长期知识”，以及读取时是否保留回到证据的路径。

图 P06A-2 要回答两个问题：编辑权放在人、当前 Agent 还是后台管线手里；自动化增加以后，系统用什么机制控制错误放大。阅读时从左向右看自动化程度，再从每一列向下看它对应的审计和一致性成本。

![图 P06A-2｜Coding Agent 的持久知识从人工规则走向自动采编](../images/P06A/P06A-2.png)

图中从左到右，自动化程度增加，系统承担的错误放大风险也随之增加。人工规则的写入慢，但权威性清楚；会中自记能快速吸收纠正，必须保持可审计；后台采编可以处理大量历史，需要额外的租约、去重、归并、来源和读取预算。三种方式可以并存：人工规则承载明确约束，自动 Memory 吸收跨任务经验，Session 保留原始证据。

### Pi 与 OpenCode：长期知识由人写成规则

Pi 的核心文档把跨 Session 的稳定指导交给上下文文件（Context Files）。启动时，它读取全局、父目录和当前目录中的 `AGENTS.md` 或 `CLAUDE.md`，若某一目录存在 `AGENTS.override.md`，就在该目录使用覆盖文件；匹配到的内容被拼入 Context。Session 的树形 JSONL、分支摘要和会话压缩（Compaction）解决历史连续性与窗口压力，扩展（Extension）则提供加入自定义 Memory 的接入面。Pi 因而把默认产品做得很克制：核心保留可审阅的项目指导，自动记忆政策由使用者或扩展决定。

OpenCode 的官方规则路径也以人维护的 `AGENTS.md` 为主，项目规则可以提交到 Git，个人规则位于全局配置目录，`opencode.json` 的 `instructions` 还能组合现有文档、glob 路径或远端文件。它的 Compaction 会把旧的活动 Context 替换为结构化摘要与近期尾部，早期 Session 消息仍然持久保存；它解决同一 Session 内怎样继续。跨 Session 的自动长期知识可以通过插件事件和自定义工具扩展。

这类方案的优势是权威边界直观。规则由人确认，可进版本库，可在代码审查中修改，团队成员看到的是同一份约束。代价也清楚：用户需要主动维护，文件可能越来越长，过期规则不会自动消失，加载范围过宽时还会占用 Context。它们承载“外显的组织知识”，自动经验形成则留给扩展层。

### Claude Code：模型边工作边维护一组本地笔记

Claude Code 将人工规则与自动 Memory 明确拆开。`CLAUDE.md` 由用户或团队编写，用于构建命令、代码规范、项目结构和必须遵守的流程；自动记忆（Auto Memory）由 Claude 根据纠正、偏好和调试经验自行维护。两者都会进入后续会话的 Context。官方文档将其定位为上下文材料，强制行为仍需配置或代码保证；内容越含糊、冲突越多，遵循效果越不稳定。

每个 Git 仓库对应一个本机 Memory 目录，多个 worktree 共享，目录以 `MEMORY.md` 为入口，并允许拆出 `debugging.md`、`api-conventions.md` 等主题文件。启动时只加载 `MEMORY.md` 的前 200 行或前 25KB，先到者为准，主题文件由 Claude 在需要时用普通文件工具读取。这是一个非常实用的渐进披露（progressive disclosure）设计：高频索引始终可见，低频细节留在磁盘，避免把所有历史常驻 Context。

Auto Memory 的文件是普通 Markdown，用户可以通过 `/memory` 浏览、编辑、删除或关闭自动记忆。“模型自己学会一些东西”由此落成一个本地可审计目录。风险在于，模型同时扮演记录者和使用者，错误抽象可能被自我强化；入口文件的开头位置具有更高可见性，旧笔记若不更新，也会和新的仓库事实竞争注意力。

### Codex：先从单次运行提炼，再做全局归并

Codex 当前公开实现采用更重的两阶段管线。根 Session 启动后，满足非临时、Memory 开启、状态数据库可用等条件时，后台任务会运行；子 Agent 不进入这条管线。任务在后台执行，不阻塞主任务，也不会立即总结每个活跃 Session。

阶段一按线程会话（thread）处理运行记录（rollout）。系统从状态数据库中领取一批符合时间与空闲条件的记录，过滤出与 Memory 有关的内容，并行调用模型生成详细原始记忆、简短 rollout 摘要和可选 slug；任务先领取租约，失败进入退避，不会在多个启动进程中重复采编。写入提示把“不产生内容”设为合法结果，并要求基于用户消息、工具证据和任务结果判断高价值信号，秘密必须清理，泛化建议和一次性状态不应进入长期记忆。

阶段二串行维护全局 Memory 工作区。它从阶段一结果中选择仍有使用价值的记录，更新 `raw_memories.md` 与 `rollout_summaries/`，以 Git 基线计算与上次成功归并之间的差异；工作区确实发生变化时，才启动一个禁止网络、无需审批、只能本地写入的内部归并 Agent，维护更高层的 `MEMORY.md`、`memory_summary.md` 与 `skills/`。阶段一适合并行提取，阶段二必须对共享知识做单写者归并，这个分工处理的是吞吐与一致性之间的冲突。

读取路径同样分层。`memory_summary.md` 的摘要先被提供给 Agent，相关任务再搜索 `MEMORY.md`，只有注册表明确指向具体经验时，才打开少量 rollout 摘要或 Skill；若还需要精确命令和错误文本，再回到原始 rollout。官方读取提示还要求对可能漂移的 Memory 做当前核验，未核验就要说明来源与陈旧风险，实际使用过 Memory 时附带机器可解析的引用。Codex 的重点不只是“能召回”，而是让未来 Agent 知道自己为什么相信这条内容。

这套方案的成本是实现复杂度。后台任务需要状态数据库、租约、重试、全局锁、选择水位、Git 基线和内部 Agent，Memory 也可能在当前 Session 结束一段时间后才完成归并。它适合历史量大、需要自动学习且强调 provenance 的产品，不适合所有轻量 CLI 都照搬。

Codex 的两阶段设计容易被“后台总结”四个字压扁。图 P06A-3 专门展开其中的并发边界：左侧许多 rollout 可以并行提取，右侧共享的长期知识只能串行归并。阅读时注意中间的交接物，它把一次运行的局部解释与全局资料的修改分开。

![图 P06A-3｜Codex 先并行提取单次运行，再由单写者归并全局 Memory](../images/P06A/P06A-3.png)

这张图的重点不在“使用两个模型调用”，而在所有权。阶段一只对各自领取的 rollout 负责，失败可以单独重试；阶段二拥有共享 Memory 工作区，必须基于同一基线处理冲突。把二者合并成许多后台任务直接改同一份 `MEMORY.md`，吞吐看似更高，却会失去确定的写入顺序、去重位置和失败恢复点。

## 从行业方案中提炼一条学习主线

学习者容易被“情景、语义、向量、图谱、反思”这些术语分散注意力。把它们重新放回一条端到端链路，会发现 Agent Memory 需要回答的远不止检索问题。LongMemEval 用 500 个问题评估了信息提取、多 Session 推理、时间推理、知识更新和拒绝回答，再加上工程系统不可缺少的作用域隔离，这六个观察面比单独的向量召回率更接近真实使用。

| 能力 | Coding Agent 中应当出现的行为 | 常见伪成功 |
|-|-|-|
| 信息提取 | 从用户纠正、测试结果和源码事实中抽取不同类型的候选 | 把助手总结当作已验证事实 |
| 多 Session 推理 | 把不同时间的决策、失败与用户反馈合并，保留冲突关系 | 只返回语义最相似的一段旧对话 |
| 时间推理 | 区分“当时通过”与“当前仍通过”，理解先后与有效期 | 用最近访问时间冒充事实发生时间 |
| 知识更新 | 新证据替换、修正或废弃旧结论，保留来源链 | 旧、新两条同时注入，让模型自行猜 |
| 拒绝回答 | 无相关或低置信度时返回空召回，转向当前源码核验 | 为了显得有 Memory 而返回最相近的噪声 |
| 作用域隔离 | 用户、仓库、分支和组织之间不串线 | 同一用户在仓库 A 的约定泄漏到仓库 B |

这张表也说明，索引只是中间层。信息提取失败时，检索再准也只能找到错误记录；更新模型缺失时，最相似的结果可能恰好是旧结论；读取端不核验时，带 provenance 的 Memory 仍然会被误用；作用域设计错误时，系统会把“个性化”变成跨项目污染。

把产品名称拿掉以后，四套方案留下五项长期稳定的责任：

| 稳定责任 | 它要做出的决定 | 轻量实现 | 自动化提高后的额外要求 |
|-|-|-|-|
| 经历留存 | 哪些原始事实值得保留 | Session 或普通日志 | 不可变原始记录、秘密清理 |
| 写入许可 | 哪些经历可以改变未来行为 | 人工编辑规则文件 | 候选分级、no-op、作用域判断 |
| 当前状态维护 | 冲突、更新和删除怎样落地 | 人直接改当前规则 | 归并、替代关系、单写者或 CAS |
| 读取投影 | 当前任务应该看到哪一小部分 | 启动时加载固定文件 | 检索、预算、渐进披露、召回许可 |
| 证据回溯 | 为什么相信这条内容 | Git 历史或可见文本 | provenance、来源游标、当前核验 |

这五项责任解释了行业比较为什么要放在 Pico 之前。Pico 不需要照搬某个产品的文件布局或后台任务数，它需要确定：Runtime 应该稳定拥有哪些时序和失败边界，Backend 又应该在哪里拥有会变化的记忆政策。后面的接口设计正是对这五项责任重新分工。

一个可工作的最小系统可以从人工规则开始，再逐步增加自动化。先让稳定约束有明确文件和作用域，让 Session 保留原始证据；随后加入候选提取，但默认要求人工确认或严格 no-op；再加入检索与分层读取，等这些边界可评测之后才做自动归并、冲突消解和反馈学习。把全部对话向量化可以快速得到搜索能力，但写入许可、更新和证据回溯仍需单独设计。

## Pico 的 Memory：运行时不替后端决定什么值得记

Pico 当前把 Memory 拆成一条窄的运行时（Runtime）契约和一个可替换的记忆后端（Backend）。Runtime 拥有 Turn、Session、Context 与生命周期，后端拥有怎样捕获来源、怎样归一化、怎样建索引、什么记录允许召回，以及怎样提供 provenance。这个边界避免 Pico 同时维护多套记忆政策，也避免一个后端为了接入而控制 Agent Loop。

Pico 的核心选择是让 Runtime 管时序和失败边界，让 Backend 管记忆政策。先把这句话写成可检查的契约：

| 契约项 | Pico Runtime | Memory Backend |
|-|-|-|
| 输入 | 当前请求、Session Key、规范化后的 Turn 消息 | Recall Query、作用域标识、Turn 消息切片 |
| 拥有的状态 | Turn 执行、Session、Context 顺序、Backend 生命周期 | 来源日志、归一化记录、索引、召回政策、provenance |
| 保证 | 在固定位置调用 recall；Session 保存后调用 store；错误向上暴露 | 按自己的政策返回有界结果；成功返回前完成合同要求的持久化动作 |
| 不保证 | 不判断每条 Memory 是否为当前事实；不证明任务收益 | 不控制 Agent Loop；不把一次检索命中升级成 Runtime 成功 |
| 空结果 | `[]` 表示本轮没有可用 Recall，Turn 可以继续 | 可以主动 abstain，不需要凑足 `top_k` |
| 部分成功 | Session 已保存而 store 失败时，保留 Session 事实并暴露失败 | 通过 Journal、重试或运维修复派生状态，不要求重放工具副作用 |

这里存在一条实际的优先级：对话事实先可靠进入 Session，Memory 再从这份事实派生。Backend store 失败会让 Turn 暴露失败，但不能抹去已经落盘的 Session，也不应通过重跑整个 Turn 来“修复” Memory。事实完整性优先于把两个状态域伪装成一次原子提交。

把文件和类名移除后，Pico 的方案可以概括为五个稳定职责：

| 稳定职责 | 回答的问题 | 当前实现落点 |
|-|-|-|
| Runtime Orchestration | recall 和 store 在 Turn 的哪个位置发生 | ContextAssembler、AgentLoop |
| Durable Conversation Fact | 哪些消息已经成为可恢复的会话事实 | SessionManager |
| Recall Projection | 哪些 Backend 结果进入本轮模型输入 | MemorySegmentBuilder |
| Memory Policy | 哪些经历写入、更新、召回并附带来源 | 配置选中的 MemoryBackend，例如 Myna |
| Failure and Lifecycle Boundary | 启动、关闭、空召回和产品故障怎样表现 | Runtime Assembly、Backend Protocol、Myna 合同 |

即使未来把 Markdown 换成数据库、调整索引或拆分类，这五项责任仍然成立。源码对象为这套架构提供当前证据。

图 P06A-4 将读路径和写路径放在同一张图里。它展示同一条 Memory 在何处进入 Context，新的经历又在何处离开 Runtime。阅读时先看上半条读路径，再看下半条写路径；蓝色部分是 Pico 可以从仓库直接核验的责任，绿色部分是 Myna Backend 合同拥有的责任，底部红线表示 Session 与 Backend 各自提交。

![图 P06A-4｜Pico Runtime 与 Myna Backend 通过窄接口组成 Memory 读写环](../images/P06A/P06A-4.png)

读路径发生在 Context 组装阶段，当前请求被送给 Backend 召回，返回的文字进入 `# Memory` Segment；写路径发生在 Session 已经保存之后，Backend 接收规范化的本轮消息切片，再完成自己的日志、导入和索引。Pico 能保证调用顺序与错误传播，不能用接口测试证明 Memory 提升了任务成功率，也不能替外部 Backend 声明生产级可靠性。

### 源码路标按请求顺序排列

此时再打开仓库，读者只需要先跟五个位置。它们按一次请求经过的顺序排列：

| 顺序 | 先看哪里 | 这一处回答什么 |
|-|-|-|
| 1 | `pico/memory_engine/backend.py` | Runtime 与任意 Backend 最多交换什么 |
| 2 | `pico/context_engine/segments/memory.py` | Recall 怎样进入本轮 `# Memory` Segment |
| 3 | `pico/agent/loop/main.py` | Session save、after-turn 与 Backend store 的先后顺序 |
| 4 | `docs/specs/myna-memory-backend.md` | Pico 与 Myna 各自拥有哪部分状态和失败修复 |
| 5 | `pico/memory_engine/consolidate/consolidator.py` | 仓库内另一套可审计的本地记忆形成政策 |

先沿 1 到 4 走完正常路径，再读 5。第五个文件帮助理解另一种 Memory Policy；Myna 的内部实现和当前正常 Turn 的 Backend 主链由独立合同拥有。

### 一次完整的 Recall 与 Store

回到贯穿全文的请求。几次 Session 以前，用户明确要求：“更新 Pico 教程时，所有发布结论必须有当前源码、测试或运行工件支撑。”后来他在同一仓库新开 Session，只说：“更新 Memory 这一章。”正常链路如下：

1. Runtime 已经为当前 Workspace 启动并绑定选定的 Backend。若配置为 Myna，`start()` 会验证当前 Pico Workspace 对应的是已初始化且健康的 Myna 仓库。
2. 新请求进入 Context 组装。Memory Segment 用当前消息作为 query，调用 `recall(...)`。Backend 在当前仓库作用域内找到那条发布口径，返回一段已经渲染好的 `Memory.text` 和来源元数据。
3. Memory Segment 把本地慢变化资料和 Backend Recall 合成一个 `# Memory` 区块。模型由此知道要核验源码与证据，但仍需实际读取当前文件，才能写出今天的测试数字。
4. Agent 完成更新后，AgentLoop 清理运行时前缀、合成恢复消息和不适合持久化的内容，把本轮消息追加到 Session。
5. `SessionManager.save(...)` 成功后，Context Engine 完成 after-turn 处理，随后 Runtime 把同一份可持久化消息切片交给 `backend.store(...)`。
6. Backend 决定这次经历是否产生新 Memory。若用户只是重复原有要求，它可以归并或 no-op；若用户修正了作用域，它可以建立替代关系。这个政策不由 Pico AgentLoop 编写。

模型最终看到的核心形状可以简化成：

```text
# Memory

- 在 Pico 教程中，发布结论必须由当前源码、测试或运行工件支撑。
  来源：先前用户纠正；作用域：当前仓库；状态：active

# Current request

更新 Memory 这一章。
```

这段示意文字只解释数据流，并非 Myna 当前固定的渲染格式。真正的 Backend 可以选择不同的文本布局，Pico 只把 `Memory.text` 拼入 Segment；来源游标等 Backend 特有字段保留在 `metadata` 中，不会原样倾倒给模型。

正常链路闭合以后，后面的五个方法、空召回和部分成功就不再是孤立接口。它们分别守住启动、读取、写入、兼容扩展和关闭这五个时刻。

### `MemoryBackend` 为什么只有五个动作

`pico/memory_engine/backend.py` 定义了运行时可检查的协议（Protocol）：

```python
async def recall(
    self,
    query: str,
    *,
    user_id: str | None = None,
    agent_id: str | None = None,
    top_k: int,
) -> list[Memory]: ...

async def store(
    self,
    session_id: str,
    messages: list[dict[str, Any]],
) -> None: ...

async def feedback(self, signals: dict[str, Any]) -> None: ...
async def start(self) -> None: ...
async def stop(self) -> None: ...
```

返回值 `Memory` 也很小：

```python
@dataclass(frozen=True)
class Memory:
    text: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

`text` 是 Backend 已经整理好、可以进入 Prompt 的文字。`score` 用于排序与诊断，不承担事实置信度；`metadata` 保存来源标识、游标或 Backend 特有信息，Host 不会把它未经处理地拼给模型。Pico 允许各 Backend 保留自己的向量、事实三元组或事件模式，因为这些政策最容易变化。相应地，Backend 必须在 `text` 中完成安全、受限、可理解的渲染；Runtime 只验证接口形状，每条事实的语义质量由 Backend 与当前任务共同核验。

Backend 交给 Runtime 时，会把丰富的内部结构压成三个字段。这个过程可以称为有损归一化：Backend 内部可能拥有事件关系、置信度、替代链和多个来源，进入 Runtime 后却只剩一段 `text`、一个排序分数和一包不透明元数据。收益是 Host 不需要理解每种 Memory 模型；代价是 Host 无法在最后一刻重新做事实合并，也不能根据统一字段替所有 Backend 修正作用域。Recall admission、冲突处理、尺寸限制和面向模型的渲染因此必须在 Backend 返回之前完成。

`metadata` 提供诊断与证据出口，却不会自动改善模型回答。若来源只存在于 `metadata`，当前 Prompt 路径不会让模型看见它；Backend 若希望模型依据来源采取不同动作，需要把必要边界安全地编入 `text`。窄接口把接入成本压低，也把语义正确性的责任推回了 Backend。

`pico/memory_engine/base.py` 也反映了这次收敛：旧的 `MemoryEngine` 抽象基类（ABC）与 `DefaultMemoryEngine` 外观层（facade）已被删除，文件只保留 `AssembledContext` 和 `TokenBudget` 两个数据载体。Host 不再依赖一个同时暴露存储、技能和上下文内部对象的大接口，插件只需要满足更窄的 `MemoryBackend`。

接口中保留 `agent_id` 与 `feedback(...)` 是兼容边界。当前 Host 只走用户通道（user lane），也没有把 Memory feedback 接成活跃闭环，因此不能把这个方法的存在写成“系统会根据使用结果自动进化”。一个可调用的空方法和一条有证据的学习闭环之间，还缺信号定义、归因、更新政策与回归评测。

### 读取只有一个入口：Memory Segment

`MemorySegmentBuilder` 是 ContextAssembler 的第 3 个 Segment，在 Phase A 与 Identity、Bootstrap、Active Skills 和 Skills 并行构建。它读取 Host 的本地 `user.md` 视图，再调用 `backend.recall(query=current_message, user_id=..., top_k=...)`，把两部分合并到一个 `# Memory` 段，`memory_hits` 进入 Context 元数据。

这个位置很关键。Memory 不直接改写用户消息，不伪装成 Session 历史，也不绕过 Context 预算成为隐藏输入；它只是本轮 system 前缀中的一个有序 Segment。后端返回空列表是正常的“没有被许可的记忆”，认证、连接或内部错误则继续向上抛出，使 Turn 失败。Pico 不把“Backend 坏了”伪装成“用户从未说过”，因为两种状态会让排障和隐私承诺产生完全不同的解释。

将 `memory.backend` 显式设为 `null` 时，Runtime 关闭 Memory recall、持久化、个性化 Memory 与 Curator Memory Tools，Session 与本地 Skill 仍然工作。这是受支持且可审计的无 Memory 模式；启动失败仍按失败传播。

当前 Segment 将 Backend 提供的 `text` 注入 Context。Myna 的 recall admission 与 provenance 可以降低错误召回，主 Agent 对漂移事实仍应回到当前源码、配置或外部系统确认。Runtime 负责注入位置和失败边界，内容可信度由来源与当前核验共同决定。

### 写入先经过 Session，再到 Backend

一次 Turn 结束后，AgentLoop 先用 `_save_turn(...)` 清理合成恢复消息、运行时前缀与不适合持久化的字段，把规范化结果追加到 Session；`SessionManager.save(...)` 成功后，Context Engine 执行自己的 `after_turn(...)`，随后 `_dispatch_backend_store(...)` 把同一份可持久化消息切片交给 `backend.store(...)`。

顺序反映了数据权威关系：Session 是发生过的对话事实，Memory 是从它派生出的长期知识。若 Backend store 失败，异常会让 Turn 以失败路径结束，但 Session 可能已经成功落盘，系统处于明确的部分成功状态。正确补救是重新导入或让 Backend 从 Journal 恢复；重新执行整个 Turn 可能重复已经产生的工具副作用。

Myna 合同把这条边界再向后延伸。`start()` 负责把当前 Pico Workspace 绑定到已经初始化的 Myna Git 仓库，并检查恢复状态、索引准备度与存活健康；`store()` 在导入和索引同步前先写来源日志（Source Journal），Journal 或索引失败都要抛出；`recall()` 返回经过许可、尺寸受限并带来源元数据的 Memory。Pico 不替用户自动初始化、迁移或切换仓库，配置错误与仓库绑定不一致按失败闭合（fail-closed）处理。

### 仓库身份为什么不由 `user_id` 选择

当前 Host 调用的是 user track，但 Myna 把它解释为当前仓库中的用户向召回，`user_id` 不负责选择 repository 或 namespace。真正的仓库身份来自运行时装配（Runtime Assembly）选择的 Workspace，以及 Myna 启动时验证的仓库绑定。

如果任意请求参数都能切换记忆库，一个错误的 chat id、插件参数或模型生成值就可能造成跨仓库读取；把仓库绑定放在 Backend 生命周期中，启动时一次验证，Turn 内只在已绑定范围内召回，隔离边界更容易审计。代价是切换 Workspace 需要重新装配和启动 Backend，不能把不同仓库当成一次 recall 的随意过滤条件。

Myna 也没有别名回退、双读或自动迁移。已选择的 Backend 缺失、无法启动或存储失败时，Pico 要求显式修复，或把 `memory.backend` 设为 `null` 关闭 Memory。静默回退到另一套旧数据虽然看起来可用，却无法说明用户当前看到的是哪一代记忆，也无法完成删除与隐私核对。

### 四个相似结果必须分开处理

沿着正常链路注入故障，可以看到这条窄接口真正保护了什么：

| 现场 | Runtime 观察到什么 | 正确解释 | 后续动作 |
|-|-|-|-|
| Backend 返回 `[]` | Recall 成功、命中数为 0 | 当前没有获准进入 Context 的 Memory | 继续任务，必要时读当前源码 |
| Backend Recall 抛异常 | Context 组装失败 | 认证、连接或后端产品发生故障 | 暴露失败并修复 Backend |
| `memory.backend = null` | 没有构造 Backend | 操作者明确选择无 Memory 模式 | Session、Context 与 Skill 继续工作 |
| Session save 后 store 抛异常 | Session 已有事实，派生写入未完成 | 明确的部分成功 | 从 Session 或 Journal 修复，避免重放工具 |

这四种状态若都降级成“没有召回结果”，系统表面上更可用，排障、删除和隐私解释却会失去可信依据。Pico 因此允许空结果，也允许显式关闭；产品故障则按故障传播。

## 仓库里的本地归并器说明了另一种记忆形成方式

`pico/memory_engine/consolidate/` 仍保留一套可读的本地 MemoryStore 与 MemoryConsolidator。它对学习很有价值，因为写入政策都能在一个文件里看到；但当前统一 ContextAssembler 声明 `owns_compaction=True`，正常 Turn 的长期存储主路径走 MemoryBackend，不能把这套归并器描述为 Myna 的内部实现或默认全链路。

本地存储把情景记录与资料快照分开：

```text
<state>/user_memory/episodic/episodes.md
<state>/user_memory/profile/user.md
```

`annotate(...)` 将一段对话提炼成带时间与内容标签的单行情景，只有 `#question`、`#habit`、`#answer` 这类过程标签而缺少主题标签的记录会在代码边界被丢弃；模型没有调用所需工具、参数形状不对或异常出现时，本轮标注失败。可选前瞻提示（Foresight）默认关闭，避免为每次归并增加预测成本与噪声。

`user.md` 保存当前资料快照，`episodes.md` 保存事件。某个标签自上次刷新后累计 5 条新情景，`maybe_refresh_hot_tags(...)` 才让模型重写一个 H2 分节；新条目必须带 `[src: episodes.md @ 时间]`，缺少来源的条目被删除。写入前还会在文件锁内比较旧内容，若其他进程已修改文件就跳过，留待后续重试。这套设计把“事件不断追加”和“当前结论原位更新”分开，也把来源检查从提示词要求提升成代码过滤。

图 P06A-5 要回答的是：为什么这套本地实现同时需要 `episodes.md` 和 `user.md`。从左侧看连续追加的经历，经过中间的热点标签门槛，再看右侧怎样只更新一个当前资料分节。

![图 P06A-5｜本地归并器把追加式 Episode 与可更新的用户资料分开](../images/P06A/P06A-5.png)

图中的 “5 条” 是当前实现的默认热点门槛，并非所有 Memory 系统的经验常数。门槛更低时，资料更新快，但一次偶然行为更容易被写成稳定偏好；门槛更高时，误写减少，真正变化也会更晚进入资料。代码选择 5，表示它愿意先积累一小组同主题证据，再付出一次模型归并成本。Foresight 默认关闭，使预测未来需求成为显式选择，普通归并无需承担这项额外成本。

旧的 token 归并路径最多执行 5 轮，并试图把 Session Prompt 收缩到 Context 窗口的一半；统一 Context Engine 由 Curator 自己管理历史后，这条路径不再是正常轮次的主要压缩所有者。它留在仓库中提醒读者：Context Compaction 与长期 Memory 可以共享素材，但承担不同目标。前者为当前模型腾空间，后者为未来任务维护知识。

## 用对抗样例判断 Memory 是否产生任务收益

Memory Demo 很容易显得聪明：存一句“我喜欢 Python”，再问“我喜欢什么语言”，命中即可。真实系统需要面对更难的组合，尤其是旧事实仍有很高语义相似度、不同项目使用相同术语、用户从未提供答案，以及工具输出试图诱导写入的时候。

一组面向 Coding Agent 的最小评测应覆盖这些样例：用户明确重复过的工作偏好应当被召回；仓库专属测试命令不能泄漏到另一个仓库；一次旧架构决策被新源码和新用户指令替换后，旧结论不应继续影响回答；一次性的测试通过结果应留在情景记录而不是长期资料；无关问题应当得到空召回；含有“忽略系统指令”的网页或工具输出不能成为未来指令；Memory 指向的文件发生变化时，Agent 应重新读取当前来源再作答。

图 P06A-6 把评测单位从“检索一次”提升为“完成一对任务”。同一个任务分别在 Memory 关闭和 Myna 开启时运行，其他条件冻结。阅读时先看 Pair 如何配对，再看右侧的三种结果：有效 Pair 可以比较能力或效率，基础设施故障使 Pair 失效，Myna 自身故障则保留为 treatment 的产品失败。

![图 P06A-6｜PicoBench 用成对实验区分任务收益、基础设施故障与 Myna 产品失败](../images/P06A/P06A-6.png)

这张图解决了一个容易制造“正向提升”的统计陷阱。若 control 恰好遇到 Provider 故障，而 treatment 正常完成，把前者记成普通任务失败会凭空抬高 Myna。PicoBench v2 将 Provider、网络传输、预算和 Benchmark 基础设施故障显式记录；任一 arm 出现这类故障，整个 Pair 不进入能力和效率结论。反过来，Myna 的启动、召回、写入或关闭失败属于 treatment 本身，必须留在能力分母里，不能借“排除异常值”被删掉。

评测记录也不应只看 Hit@k。写入端需要观察候选精度、no-op 是否正确、来源覆盖和秘密泄漏；检索端需要观察相关性、作用域隔离、旧知识冲突与拒绝率；读取端需要观察最终任务是否减少无效工具调用、是否更快找到正确文件、是否在事实漂移时完成核验。还要记录延迟、模型调用与存储成本，否则一个提高一点命中率却让每轮多跑后台 Agent 的方案，未必符合产品预算。

### A/B 实验怎样只改变 Memory

PicoBench 的 Myna task-effect 实验使用一个很窄的 treatment axis：

```text
control:   memory.backend = null
treatment: memory.backend = myna
```

每个 Pair 冻结 Pico 与 Myna 的候选制品、任务、仓库 fixture、Prompt、Provider 或确定性策略、Tools、Context 预算、Turn 预算和外部 Verifier。treatment 不获得额外工具、token、重试或超时。顺序按固定种子在 AB 与 BA 之间轮换，避免“总是先跑 control”把缓存或环境顺序带进结果。

真实 Memory 效果必须跨过进程和 Session 边界。treatment 先运行一次 prior Turn，让经历经过 `start → recall → store → stop`；随后在新进程、新 Session 中再次执行 `start → recall → evaluation Turn → store → stop`。control 执行相同的 prior Turn 与 evaluation Turn，Memory Backend 保持关闭。最终任务成功由父进程 Verifier 检查产物，Agent 的自述不参与判定。

Pair 的意义是让同一个任务充当自己的对照。一个本来就容易的任务可能在两臂都成功，一个困难任务可能都失败；直接比较两组互不相干任务，会把任务难度误当成 Memory 效果。AB/BA 轮换再控制运行顺序，使缓存预热、临时环境状态或 Provider 时序不总是偏向同一臂。

同一任务的多次 repetition 也不能当成完全独立的新知识。它们共享任务结构、Verifier 和所需事实，结果往往相关。因此区间按任务聚类，而不是把每个 Trial 当作独立样本。平均值描述这次运行观察到多少变化；聚类区间描述换一批同类任务时，这个方向有多稳定。两者回答不同问题，都需要保留。

每次实际 Backend 调用还会留下 operation receipt。只有 awaited 方法成功返回，`start`、`recall`、`store` 或 `stop` 才能进入成功摘要；失败 receipt 保存阶段、操作名和结构化错误。这样可以证明本次 treatment 真的发生过哪些 Memory 操作，也能防止 Scheduler 没有返回结果时凭空补出一次 store。

### 已完成的确定性实验说明了什么

确定性正式实验包含 72 个 Pair、144 个 Trial。Memory 关闭和 Myna 开启两臂都是 72/72 任务通过，Myna arm 的 repository read 平均减少 50.0%。按任务聚类得到的 95% 区间是 29.17% 到 70.83%，没有观察到 stale-memory 回归或跨仓库 Memory 事件。

这项结果支持一个范围很窄但成立的结论：在冻结的确定性任务包和已安装候选制品上，Myna 让 Agent 少做了仓库重复读取，同时没有降低这些任务的成功率。两臂任务成功数完全相同，因此能力提升为零。网络 Provider 调用在该实验中被禁止，结果只覆盖本地确定性工作负载。

这里的 50.0% 是 72 个成对任务上的平均 repository-read reduction。区间回答另一个问题：若把任务类别的差异考虑进去，当前样本支持的真实平均改善可能落在哪个范围。区间下界仍高于零，所以这项冻结工作负载上的效率结论通过门槛；对其他 Coding Agent 任务的效果仍需新的样本验证。

### 真实 Agent 子轨给出了方向，没有通过正向声明门槛

轻量 real-Agent 子轨运行了 24 个 Pair、48 次 DeepSeek Trial，24 个 Pair 都满足比较条件。control 通过 5/24，Myna 通过 10/24，观测到的通过率差是 20.83 个百分点；任务聚类 95% 区间为 0 到 41.67 个百分点。stale-memory 回归和跨仓库 Memory 事件仍为 0。

平均值可以报告，但它不能独自回答结果是否稳定。这里区间下界碰到 0，表示在当前 12 个任务的轻量样本上，重复抽取任务簇时仍可能得到“没有提升”的结果。实验因此被标记为 measurement-valid 的探索性方向，capability、general-Agent 和 overall positive claim 都未通过。只有 4 个 Pair 在两臂同时成功，输入 token 反而增加 18.13%，Tool Call 增加 5.95%，效率门槛也没有通过。

这正是评测系统应该表现出的克制：它完整记录了一个看起来很好看的平均差值，同时拒绝把它升级成“Memory 将 Agent 成功率提高 20.83%”。更稳妥的表述是，冻结的轻量任务包观察到正向方向，样本规模和不确定性尚不足以支持能力声明。

### Myna 的 LoCoMo 诊断是另一类问题

PicoBench task-effect 问的是“接入 Pico 后，Memory 是否帮助 Agent 完成跨 Session 的代码任务”。LoCoMo 问的是“Memory 系统能否从长期对话中回答信息提取、跨 Session 推理、时间、更新和开放域问题”。两者共同研究 Memory，但指标不能拼成一个分数。

当前 Myna LoCoMo 诊断运行了 200 个 live DeepSeek 问题，答对 139 个；按自然类别权重计算的准确率是 77.04%，基础设施失败为 0，retrieval P95 为 3.626 秒。预先冻结的晋级门槛是 82%，所以这次诊断没有获准继续 1,540 题正式运行，也没有产生可作为 headline 的 LoCoMo 分数。

这项失败仍然有信息量。它说明端到端运行和证据重建能够完成，也明确显示当前候选低于预设质量门槛。若只写“139/200”或只写“77.04%”，读者会失去为什么停止、是否完成全量评测以及能否公开比较的边界。

### 三个状态要分开读

| 证据轨 | `ship_complete` | `measurement_valid` | `positive_claim_eligible` | 可以怎样说 |
|-|-|-|-|-|
| 确定性 Myna task-effect | 完成 | 有效 | 仅冻结任务包的效率声明通过 | repository read 平均减少 50.0%，能力无提升 |
| real-Agent Myna task-effect | 完成 | 有效 | 未通过 | 观察到 +20.83 个百分点方向，区间包含 0 |
| Myna LoCoMo 200 题诊断 | 完成诊断 | 有效 | 未通过晋级门槛 | 77.04% 诊断结果，未运行 1,540 题正式集 |

`ship_complete` 只说明计划中的运行和工件是否齐全；`measurement_valid` 说明失败分类、Pair、Verifier 与制品身份能否支撑统计；`positive_claim_eligible` 才决定能否对外给出正向效果结论。三者分开以后，一个实验可以工程上完整、测量上可信，同时诚实地得出“当前证据不足”。

### 从保证反推测试

Pico 当前测试把前文的关键边界逐项锁住：空 Recall 是合法结果；Memory Segment 将 Backend 文本合并到一个 `# Memory` 段；Recall 硬故障向上抛出；完整 Turn 的 recall、注入和 store 顺序可观察；store 失败发生在 Session 保存之后；Provider 或基础设施故障使 Pair 失效；Myna Backend 故障保留为 treatment 产品失败；失败 Turn 不伪造 store receipt；旧版实验摘要不能被悄悄升级成新版 operation evidence。

这些测试证明接口、顺序、分类和证据重建在被测路径上成立。它们仍不能代替真实任务效果，也不能证明外部 Backend 的生产可靠性。任务收益由成对实验观察，跨环境泛化需要更大的确认性任务集，发布与运维状态则需要独立的制品和现场证据。

对 Pico 的源码阅读可以按数据流进行：从 `backend.py` 看 Host 与 Backend 能交换什么，再到 `context_engine/segments/memory.py` 看召回怎样进入 Context，随后在 `agent/loop/main.py` 找到 Session 保存与 `store(...)` 的顺序，再用 `docs/specs/myna-memory-backend.md` 核对两侧所有权，接着阅读 `consolidate/` 与 `contract_test.py`，分别理解另一种可审计的形成政策，以及接口测试究竟证明了什么。最后打开 PicoBench 的任务效果规范，把接口保证和实验观察重新对齐。

沿着这条路径，Pico 的 Memory 架构可以用一段不依赖类名的话复述：Harness 在每次任务的固定位置请求和写回 Memory，先保存可恢复的会话事实，再把派生知识交给 Backend；Backend 拥有作用域、索引、归并、召回许可和来源；空结果可以继续，产品故障必须暴露，部分成功通过证据修复；效果则由只改变 Memory 的成对实验单独证明。

## 参考资料

- [Pico ](https://github.com/Hackerismydream/pico/blob/main/CONTEXT.md)[`CONTEXT.md`](https://github.com/Hackerismydream/pico/blob/main/CONTEXT.md)：Session、Turn、Context、Memory Backend 与 Runtime Assembly 的规范术语。
- [Pico State and Intelligence Architecture](https://github.com/Hackerismydream/pico/blob/main/docs/architecture/state-and-intelligence.md)：Session、Curator、Memory、Skill 与 Trace 的状态归属和失败边界。
- [Pico Runtime Architecture](https://github.com/Hackerismydream/pico/blob/main/docs/architecture/runtime.md)：一次 Turn 中 Context、Session save、Memory store 的实际执行顺序。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/backend.py)[`memory_engine/backend.py`](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/backend.py)：`Memory` 数据载体与 `MemoryBackend` 五个生命周期动作的公开合同。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/base.py)[`memory_engine/base.py`](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/base.py)：已删除旧 MemoryEngine facade，仅保留 Context 组装所需的数据载体。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/context_engine/segments/memory.py)[`context_engine/segments/memory.py`](https://github.com/Hackerismydream/pico/blob/main/pico/context_engine/segments/memory.py)：Host Memory 与 Backend recall 怎样合成第 3 个 `# Memory` Segment。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/context_engine/factory.py)[`context_engine/factory.py`](https://github.com/Hackerismydream/pico/blob/main/pico/context_engine/factory.py)：统一 ContextAssembler 对 Curator、Memory 与 Local Skill 三条 lane 的装配。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/context_engine/assembler.py)[`context_engine/assembler.py`](https://github.com/Hackerismydream/pico/blob/main/pico/context_engine/assembler.py)：Memory Segment 的并行构建位置，以及当前 Context Engine 对历史压缩所有权的声明。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/agent/loop/main.py)[`agent/loop/main.py`](https://github.com/Hackerismydream/pico/blob/main/pico/agent/loop/main.py)：规范化 Turn 切片、Session 持久化、Context after-turn 与 Backend store 的主链。
- [Pico Myna Memory Backend Contract](https://github.com/Hackerismydream/pico/blob/main/docs/specs/myna-memory-backend.md)：Pico 与 Myna 的所有权、仓库绑定、Journal、索引和 fail-closed 合同。
- [Pico ](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/consolidate/consolidator.py)[`consolidate/consolidator.py`](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/consolidate/consolidator.py)：情景日志、资料快照、标签触发、来源过滤与并发写保护的本地实现。
- [Pico Memory Backend Contract Tests](https://github.com/Hackerismydream/pico/blob/main/pico/memory_engine/contract_test.py)：跨 Adapter 可由 CI 验证的返回类型、top-k、生命周期与空召回边界。
- [PicoBench Myna Task Effect](https://github.com/Hackerismydream/pico/blob/main/docs/evaluation/picobench-myna-task-effect-v1.md)：确定性与 real-Agent 成对实验、operation receipt、失败分类和声明门槛。
- [Pico Candidate Evidence Index](https://github.com/Hackerismydream/pico/blob/main/docs/evaluation/candidate-evidence-index.md)：候选制品、正式结果、工件摘要与可对外使用的证据边界。
- [Pi Coding Agent README](https://github.com/earendil-works/pi/blob/086c32e74530564922d011ade23ff582c9d63116/packages/coding-agent/README.md)：Context Files、Session、Compaction 与 Extension 的官方产品边界。
- [Pi Sessions](https://github.com/earendil-works/pi/blob/086c32e74530564922d011ade23ff582c9d63116/packages/coding-agent/docs/sessions.md)：树形 Session 与 Compaction 解决历史连续性，而不是自动长期知识采编。
- [Claude Code Memory](https://code.claude.com/docs/en/memory)：`CLAUDE.md`、Auto Memory、本机目录、200 行或 25KB 启动读取上限与 `/memory` 审计入口。
- [Codex Memories README](https://github.com/openai/codex/blob/85fc4def358b7df21883e72ae8dda43a0f572f32/codex-rs/memories/README.md)：Phase 1 rollout extraction 与 Phase 2 global consolidation 的当前公开架构。
- [Codex Phase 1 Memory Writer Prompt](https://github.com/openai/codex/blob/85fc4def358b7df21883e72ae8dda43a0f572f32/codex-rs/memories/write/templates/memories/stage_one_system.md)：no-op、证据优先、秘密清理、用户偏好与任务结果判定的写入政策。
- [Codex Memory Read Path](https://github.com/openai/codex/blob/85fc4def358b7df21883e72ae8dda43a0f572f32/codex-rs/ext/memories/templates/memories/read_path.md)：从 summary 到 registry、rollout 与 Skill 的渐进读取、核验和引用要求。
- [OpenCode Rules](https://opencode.ai/docs/rules/)：项目与全局 `AGENTS.md`、Claude Code 兼容规则和 `instructions` 配置的官方说明。
- [OpenCode Compaction](https://opencode.ai/v2/docs/compaction)：Session 内结构化 checkpoint、近期尾部与 Context overflow 恢复的边界。
- [OpenCode Plugins](https://opencode.ai/docs/plugins/)：通过本地或 npm 插件挂接事件、自定义工具与外部 Memory 服务的扩展面。
- [CoALA: Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)：用模块化 Memory、内部动作和外部动作组织 Language Agent 的认知架构框架。
- [Generative Agents](https://arxiv.org/abs/2304.03442)：Memory Stream、基于相关性与时间的检索、Reflection 与 Planning 的代表性研究。
- [MemGPT](https://arxiv.org/abs/2310.08560)：把有限 Context 与外部存储建模为分层虚拟 Memory 的经典方案。
- [LongMemEval](https://arxiv.org/abs/2410.10813)：以信息提取、多 Session 推理、时间推理、知识更新与拒绝回答评估长期交互 Memory。
