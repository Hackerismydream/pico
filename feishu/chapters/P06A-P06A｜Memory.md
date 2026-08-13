# P06A｜Memory

<callout emoji="💡">
**Memory 是 Agent 获得跨 Session 连续性的基础设施。 Session 保存已经发生的对话，项目文档保存人明确维护的规则；Memory 则从历史中筛出可能长期有用的信息，并在新请求出现时召回。它让 Agent 不必每次重新认识用户和项目，也可能把一次误判放大成长期影响。因此，Memory 同时是一条信任链路：写入前判断值不值得记，使用前判断现在还能不能信。**
</callout>

> 小林昨天说：“以后评测报告的图片放到仓库外。”今天他只说：“继续整理评测结果，还是按之前的习惯。”Agent 要找到那条偏好，但更难的问题在前后两端：昨天那句话是否值得长期保存？今天取回它以后，是否仍然有效？

Memory 让一次会话里获得的信息，在未来另一次会话中继续发挥作用。它的质量并不取决于“存了多少”，而取决于写入时过滤了什么、召回后又怀疑了什么。一条错误推断如果长期存在，影响的可能不是当前一次回答，而是后面许多次决策。

## 先把四种跨 Turn 信息分开

| 信息域 | 保存什么 | 以后怎样使用 |
|-|-|-|
| Session | 原始对话消息、工具调用与结果 | 按会话恢复历史，回答“之前发生了什么” |
| 人工文档 | 人明确维护的规则、架构与约定 | 按项目或目录加载，拥有清楚的人工控制面 |
| 自动 Memory | 系统从历史中提取、以后可能有用的稳定信息 | 根据新请求召回，并在使用前检查相关性和时效性 |
| Skill | 完成一类任务的方法、步骤与工具使用约束 | 匹配任务后指导行动；详细机制见 P06B |

从广义看，人工文档也在帮助 Agent “记住”项目。但本章把自动 Memory 单独拿出来，因为它会自行提取、更新和召回，错误也更容易在无人注意时积累。用户明确写进 `AGENTS.md` 的规则，和模型从一次偶然行为中推断出的偏好，可信等级不能相同。

## 一条 Memory 要走完七个动作

1. 捕获：从对话、工具结果或其他事件中拿到候选信号。
2. 筛选：判断它是否稳定、可复用，而且无法从当前权威资源轻易重新获得。
3. 持久化：写入文件、数据库、日志或外部 Memory 服务。
4. 整合：去重、合并冲突、更新旧结论、压缩索引。
5. 召回：用新请求找到可能相关的候选。
6. 核实：检查来源、时间、作用域和当前事实，决定是否采用。
7. 反馈：根据使用结果修正、降权或遗忘。

很多实现只做了“持久化 + 召回”，于是 Memory 越积越多，错误也越积越久。成熟方案把筛选和核实做成独立关口：写入门决定记不记，信任门决定用不用。

## Claude Code：快速写入，再用 Dream 做慢速整理

Claude Code 使用文件式 Memory：一个简短的 `MEMORY.md` 负责索引，具体条目放在独立 Markdown 文件中。它还区分 private 与 team 两种作用域，并把内容分成 user、feedback、project、reference 等类型。索引被放进上下文，具体文件则在模型判断相关后再读取。

它有两条快速写入路径。一条发生在主 Session 中：模型遇到值得长期保留的信息时主动更新。另一条发生在回合结束后：系统启动受限的 fork session，从最近一段对话中抽取候选。这两条路径都追求及时性，让“刚刚学到的偏好”尽快在下次会话生效。

快速写入的风险也很直接：模型可能把临时状态、一次性选择或错误解释保存下来。因此它花了很大篇幅规定什么不能存，例如：

- 能从当前代码、项目文件或 Git 历史重新获得的事实；
- 已经写进人工维护文档的规则；
- 当前任务的临时进度和只对本次对话有用的信息；
- 凭据、密钥或不该进入共享团队记忆的敏感内容；
- 尚未被用户采纳的猜测和探索性提议。

文章还介绍了一个默认未开启的 Dream 整合流程。它周期性检查 Memory、近期活动日志和必要的 Session 片段，把重复条目合并，修正已经漂移的事实，清理索引，并让索引保持在可注入的长度内。Dream 处理的是记忆整理，不是模型重新训练，也不等于 Agent 获得了自动进化能力。

## Codex / OpenAI Agents SDK：先从 rollout 挖掘，再分两阶段整合

我们把 Codex 与 OpenAI Agents SDK 放在一起讨论，因为两者采用了相近的 Memory 思路，SDK 侧可以模块化配置。它们没有把主 Agent 的每次观察都直接写成最终 Memory，而是在新会话启动时回看历史 rollout，并把生成过程拆成两个阶段。

**Phase 1** 面向单个 rollout。较小模型并行提取原始记忆与 rollout 摘要，重点寻找稳定的用户偏好、高杠杆流程、可靠的任务地图和反复出现的失败防护。它有明确的最低信号门：如果这次对话只是一次性问题、普通状态更新或没有可复用经验，就返回 no-op，不制造记忆。

**Phase 2** 面向整个记忆工作区。它把新增 raw memory 合并进已有结构，处理重复与冲突，生成几种不同粒度的产物：

- `memory_summary.md`：始终注入的高密度导航；
- `MEMORY.md`：可以按关键词搜索的聚合手册；
- `rollout_summaries/`：保留一次任务中真正可复用的证据和经验；
- `skills/`：当历史中出现稳定、可重复的工作流时，沉淀为独立流程。

这里的 `skills/` 表示 Memory 挖掘可以产出 Skill 候选，并不表示运行时 Memory 和 Skill 使用同一条召回路径。Memory 保存过去学到的稳定信息；Skill 负责指导未来怎样行动。

Codex 的召回采用渐进式披露：先看摘要，再搜索 `MEMORY.md`，只有明确命中时才打开一两个 rollout summary 或 Skill。它还要求对容易漂移的事实重新验证。批量挖掘让结果更稳定，但学习速度慢，流程也比即时写入复杂。

## OpenClaw：日记、混合检索和可选的分层整合

OpenClaw 默认方案更接近 RAG。它先保存自由格式的每日 Memory，并用 SQLite 建索引。写入有两个入口：Agent 主动更新日记；Context 即将压缩前再触发一次提取，避免有价值的信息随窗口压缩一起丢失。

召回时同时使用关键词和向量检索，并加入时间衰减，让旧记忆逐步降低影响。可选的 `active-memory` 插件会引入 subagent 做主动、多轮召回。另一个默认关闭的 `memory-wiki` 使用独立存储区，以实体、概念等对象组织内容，可以与普通 Memory 一同召回。

OpenClaw 还存在由心跳触发的 light、REM、deep 整合阶段。按照文章的源码分析，这部分主要做文本切分、关键词匹配、文本相似度和容量控制，并非由 LLM 完成。额外生成的 `DREAMS.md` 是第一人称散文式日记，不参与 Memory 召回。阶段名称很形象，但判断实现能力仍要看输入、算法、输出和默认开关。

## 没有原生自动 Memory 也是一种选择

OpenCode、Pi 和 Kimi Code 版本没有原生自动 Memory。它们仍然可以依赖人工项目文档，或者把能力交给第三方插件。例如文章提到部分 OpenCode Memory 插件采用类似 Claude Code 的文件方式，`opencode-mem` 还加入了向量召回。

这说明，Harness 可以只提供扩展点和稳定的 Context 注入边界，把“什么值得记、怎样检索”交给外部组件。没有内置自动 Memory，不代表完全无法跨 Session 保留信息；它意味着治理政策不由 Harness 核心统一承担。

**图 P06A-A｜三种 Memory 写入与整合节奏**

从上到下看三条时间线：Claude Code 先快写、再可选慢整合；Codex 先积累 rollout、再批量提取；OpenClaw 先形成日记和索引，再由可选阶段整理。图中虚线都是可选路径，不应写成默认能力。

![](images/P06A/img1.jpg)

无论采用文件还是数据库，系统都要在及时性、整合质量、运行成本之间做取舍。快写入能尽快学会一条偏好，也更容易误记；慢整合擅长去重和纠错，却可能等到下次会话才生效。

## 文件索引与向量 RAG 解决的不是同一道题

Claude Code 和 Codex 的共同点是先给模型一个短索引，再按需打开具体条目。它适合单个用户或项目中数量有限、价值密度高的记忆。目录结构和文本标题本身就携带语义，模型也能在读取时理解较长的上下文。

OpenClaw 的关键词与向量混合检索更适合候选规模较大、查询表达和原文差异明显的情况，但它必须额外处理切分、embedding、排序、时间衰减和误召回。向量库扩大了候选搜索能力，没有自动解决冲突、过期和可信度。

因此选型时应先问数据形状：Memory 有多少、更新多快、能否按主题组织、错召回的代价多高。把所有方案都换成向量检索，往往只是更换存储与排序手段，写入门和信任门依然存在。

## 召回之后，先过信任门

一条 Memory 命中当前 query，只说明它“看起来相关”。真正使用前还要检查：

- **来源：**这是用户明确要求、Agent 推断，还是第三方内容？
- **时间：**它描述的是稳定偏好，还是某一天的仓库状态？
- **作用域：**属于当前用户、当前团队、当前仓库，还是另一个环境？
- **冲突：**它是否和用户刚刚说的话、当前代码或权威文档矛盾？
- **风险：**如果采用错误，会影响措辞，还是会触发真实写入和删除？

Claude Code 与 Codex 的设计都要求：Memory 中的文件名、函数、配置和仓库状态只是过去某个时刻的观察。成本低时，应读取当前资源重新核实。用户的新决定和当前源码优先于旧记忆。

**图 P06A-B｜一条 Memory 的可信使用闭环**

先读左边的写入门：没有长期价值的内容留在 Session。再读右边的信任门：召回候选可以被丢弃、更新或转去检查当前事实；只有通过后才进入 Context 并影响行动。

![](images/P06A/img2.jpg)

这个闭环里有两个独立判断。相关性排序回答“哪条最像当前问题”，信任判断回答“这条现在能不能用”。把二者合成一个 score，系统很难解释为什么一条高相似度旧结论被拒绝。

---

## 回到 Pico：Harness 只规定 Host 合同

Pico 当前没有把 Claude Code、Codex 或 OpenClaw 的整套 Memory 政策写进核心。它定义一个很窄的 `MemoryBackend` Protocol，让外部 Adapter 决定怎样抽取、整合、检索和持久化：

```text
recall(query, user_id, agent_id, top_k)
store(session_id, messages)
feedback(signals)
start()
stop()
```

当前默认配置是 `memory.backend="myna"`。Pico 从 `pico.plugins` 发现贡献，校验官方 `myna-memory` 身份，构造 Adapter，并由 `RuntimeAssembly` 管理 start 与 stop。Myna 未安装、身份不匹配或仓库未初始化时，启动明确失败，不会悄悄切到另一个后端。

## 沿一条 Turn 看 Pico 的读取与写入

| 源码位置 | 当前职责 |
|-|-|
| `pico/config/pico.py::MemoryConfig` | 选择 backend、user id 与 top-k；设为 null 时关闭隐式 Memory 路径 |
| `pico/cli/_plugin_stack.py` | 发现插件、校验 Myna 身份、构造并保护 backend |
| `pico/cli/_runtime_assembly.py` | 管理 backend 的异步启动、关闭与失败传播 |
| `pico/context_engine/segments/memory.py` | 用当前消息调用 recall，并记录命中数量 |
| `pico/context_engine/segments/render.py` | 过滤空白 text，把召回结果包进 UNTRUSTED 围栏 |
| `pico/agent/loop/main.py` | Session 保存后，把清理过的当轮消息 slice 交给 store |

Turn 前，`MemorySegmentBuilder` 用当前用户消息调用：

```python
await backend.recall(
    query=current_message,
    user_id=configured_user_id,
    top_k=memory_top_k,
)
```

当前默认 `user_id` 是 `default`，`memory_top_k` 是 5。user id 表示公开接口上的用户召回轨道；Myna 仍按 Workspace 对应的 Git 仓库绑定自己的数据，不把 user id 当作仓库命名空间。

Backend 返回不可变的 `Memory(text, score, metadata)`。Pico 只把非空 `text` 放进 `# Memory`；score 和 metadata 保留给 Adapter 表达相关性与来源。Host 不猜测私有 metadata，也不替 Adapter 做二次语义整合。

召回文本进入 Prompt 前会经过 `wrap_untrusted()`，形成带随机 nonce 的围栏。这个围栏降低召回文本冒充系统指令的风险，但不会证明内容真实。来源、时效、冲突与当前状态核实，仍然属于信任门。

Turn 后，Agent Loop 先保存 Session，再运行 `ContextEngine.after_turn`，随后调用 `MemoryBackend.store()`。store 收到的是经过 `sanitize_persisted_payload()` 处理的当轮消息 slice；运行时前缀、召回 Memory 和 Skill 正文不会因为出现在模型输入里，就被整块倒回后端。

```text
SessionManager.save
→ ContextEngine.after_turn
→ MemoryBackend.store
```

这个顺序留下一个可观察的失败状态：Session 可能已经保存，而 Memory store 随后失败。此时对话历史存在，长期记忆写入没有完成。恢复时应先核对已经发生的工具副作用和 Session，不能把整个 Turn 当作从未执行。

## Pico 当前没有替 Adapter 承诺什么

从 Host 源码只能确认 Protocol、调用顺序、安全围栏、插件身份和生命周期。下面这些能力不能因为其他 Harness 有，就写成 Pico 或 Myna 当前已经具备：

- 回合内快速写入与离线 Dream 双层记忆；
- Codex 式两阶段 rollout 挖掘；
- 关键词与向量混合召回、时间衰减或知识图谱；
- 自动冲突消解、过期淘汰和基于结果的自我纠错；
- 把 Memory 自动生成 Skill 并直接激活到生产环境。

这些属于 Adapter 策略或未来演进方向，需要 Myna 自己的源码、测试和工件证明。Pico 的 `feedback()` 允许实现为空操作，当前共享 Host 热路径也不会主动派发它。因此 Protocol 存在反馈入口，不等于已经形成“任务结果 → 纠错 → 新记忆”的闭环。

`memory.backend=null` 会关闭隐式 recall、store、个性化和 Curator Memory 工具，同时保留 Session、Curator state 与 Local Skills。关闭 Memory 不会清空其他状态域。

## 故障时怎样读状态

| 情况 | Pico 行为 | 已经成立的事实 |
|-|-|-|
| recall 返回空列表 | 正常继续，`memory_hits=0` | 本次没有可用候选，不代表 backend 故障 |
| recall 抛出连接或认证错误 | Context 组装失败 | Memory 路径不可用，错误被显式暴露 |
| Myna 未初始化 | backend start 失败 | Runtime 没有进入假可用状态 |
| Session 已保存，store 失败 | 错误继续向上传播 | 会话存在；长期 Memory 写入未完成 |
| `memory.backend=null` | 跳过 Memory 路径 | Session、Curator state、Local Skills 继续工作 |

## 从测试验证理解

- `tests/test_memory_backend_protocol.py`：五方法 Protocol 与 runtime check；
- `tests/test_memory_backend_contract.py`：Adapter 共享合同；
- `tests/test_segments.py`：recall、空结果、metadata 与 UNTRUSTED 渲染；
- `tests/test_agent_loop_memory_pipeline.py`：Session、after-turn 与 store 顺序；
- `tests/test_cli_runtime_assembly.py`：start/stop 幂等与失败传播；
- `tests/test_cl1_plugin_stack.py`：Myna 身份、初始化 Guard 与 fail-closed 构造。

## 25 分钟练习

1. 把开头“小林的偏好”分别放进 Session、人工文档和自动 Memory，说明三种保存方式的可信度与更新人。
2. 在 Claude Code、Codex、OpenClaw 三种方案中，各找出一个写入门和一个慢速整合入口。
3. 在 Pico 源码中从 `MemoryConfig` 追到 `MemorySegmentBuilder._recall()`，记录 query、user id、top-k 的来源。
4. 在 `render_recalled_memory()` 找到空白过滤与随机 nonce 围栏，解释它能防什么、不能证明什么。
5. 回到 Agent Loop，确认 Session save 与 backend store 的顺序，并写出 store 失败后的恢复检查清单。

## 本章复盘

- [ ] 能区分 Session、人工文档、自动 Memory 与 Skill

- [ ] 能说出 Capture、筛选、整合、召回、核实和反馈各自解决什么问题

- [ ] 能比较 Claude Code、Codex 和 OpenClaw 的写入与整合节奏

- [ ] 知道文件索引与向量 RAG 只是不同检索取舍

- [ ] 能解释为什么相关性命中之后还要经过信任门

- [ ] 知道 Pico 拥有 Host 合同和生命周期，Adapter 拥有 Memory 策略

- [ ] 不会把外部 Harness 的能力写成 Pico 或 Myna 已实现

## 接下来读什么

- [P06B｜Pico Skill 设计](https://icnoljnkix43.feishu.cn/wiki/QSHJwwkixiMVbskoGDac5uitn1e)：本地 `SKILL.md` 怎样被发现、索引、选择和注入；
- [P07｜Tools 与执行边界](https://icnoljnkix43.feishu.cn/wiki/FvphwDl6AipgzMkozHNc3kQAnib)：Memory 或 Skill 影响模型决策后，真实操作怎样执行；
- [P11｜PicoBench](https://icnoljnkix43.feishu.cn/wiki/XTOEwv9vhig1IikThC8cOJXEnrg)：怎样用可冻结的评测证明 Memory 真的改善任务，而不只证明发生过召回。