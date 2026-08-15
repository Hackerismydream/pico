<!-- Source: https://icnoljnkix43.feishu.cn/wiki/ANCdwqIyJiN95vkIwGqcwbAAn8c; Feishu revision: 361; synced: 2026-08-15. Text snapshot only; embedded Feishu images are not committed. -->

# P05｜Session 与恢复

Agent 正在修改认证模块，已经读过多份配置、调用过测试工具、写入了几处代码，终端进程却在模型给出最终回复前消失。

重新启动后，历史消息能不能重新显示，只是最浅的一层；磁盘上的文件可能已经改变，某个外部接口可能已经被调用，末尾一条持久化记录可能只写了一半，记忆后端（Memory Backend）可能还没有接收这一轮的新事实，发往用户界面的投递（Delivery）也可能在传输途中失败。此时输入一句“继续刚才的工作”，究竟应该恢复哪一种状态，哪些动作能够重放，哪些动作只能承认结果未知，这才是会话与恢复真正困难的地方。

可以把一次 Agent 执行看成一场有工具参与的实验，会话（Session）像实验记录簿，检查点（Checkpoint）像实验台在某个时刻的照片，正在运行的 Python 进程则保存着实验员脑中尚未落笔的动作序列。

记录簿可以重新读取，照片可以用来核对现场，脑中的程序计数器通常会随进程一起消失。恢复系统要做的，**不是把三者假装成同一种存档，而是承认它们有不同的持久化边界**，再从仍然可信的证据中构造下一步。

<callout emoji="💡">
恢复能力由最弱的状态域决定，有点类似木桶效应
</callout>

一次轮次（Turn）由智能体循环（Agent Loop）组织，从入站请求开始，经过多次迭代（Iteration），也就是一次模型调用及其后续工具执行，直到生成终态回复；这个过程中至少存在五类状态，它们的来源、寿命和恢复方式并不相同。

> [飞书图像未纳入仓库快照] 图 P05-1｜一次 Agent 轮次同时跨越五个状态域

图 P05-1 中，会话保存已经发生过的对话事实，上下文（Context）是当前模型调用从这些事实中选择出来的工作视图，工作区保存文件结果，进程内状态保存尚未提交的循环位置，外部副作用（external side effect）则存在于 Agent 进程之外。恢复时能够重新构造的是有持久证据的部分，不能因为一条历史消息里出现过工具调用，就推断那个调用可以安全再执行一次。

## 一、会话保存的不是“整个 Agent”

会话最容易被理解成聊天记录，这个理解没有错，却远远不够。

对普通聊天应用来说，用户消息和助手回复基本就是产品状态；

对 Agent 来说，一条助手消息可能发出工具调用（Tool Call），工具调用可能改写文件、启动进程、提交工单或发送通知，随后工具结果（Tool Result）又进入下一次模型调用。**会话因而承担的是事实账本，而不是运行中对象的序列化副本。**

| 状态域 | 典型内容 | 常见事实源 | 进程退出后能否直接恢复 | 安全的继续方式 |
|-|-|-|-|-|
| 会话 | 用户消息、助手消息、工具调用、工具结果、元数据 | JSONL、数据库、远端线程存储 | 通常可以 | 重新读取并验证完整性 |
| 上下文 | 系统指令、被选中的历史、记忆召回、工具定义 | 每次模型调用前动态组装 | 不应直接复用旧请求体 | 从当前配置与会话重新组装 |
| 工作区 | 文件内容、目录结构、Git 状态、生成物 | 文件系统、检查点、版本库 | 文件结果通常仍在 | 比对现场，必要时回退或继续 |
| 进程内执行 | 当前迭代、重试计数、流式缓冲、锁、待投递事件 | 内存 | 通常不可以 | 从持久化边界启动新的轮次 |
| 外部副作用 | 已发送邮件、已创建工单、已扣款、远端部署 | 外部系统自身 | 结果可能存在但本地未知 | 查询、对账、幂等重试，而非盲目重放 |

这张表给出了 Agent 恢复时需要面对的完整状态地图，为了方便大家理解，我通过讲解三个容易搞混的问题带大家感知一下

### 重新加载 Session，会把全部历史原样交给模型吗？

不会。**Session 保存的是已经发生过的对话事实，Context 则是当前这一次模型调用的工作视图。**

会话应尽量保留完整、按序追加的用户消息、助手消息、工具调用和工具结果，以便审计、分叉和重新组装。Context 受到上下文窗口、当前任务和工具协议的限制，只会从会话中选择一部分历史，再叠加系统指令、记忆召回、工具定义与本轮输入。

因此，“重新加载会话”不能直接等价为“把全部历史重新发送给模型”。否则长会话会重新出现上下文膨胀、工具调用与工具结果配对破坏，以及摘要漂移等问题。

Pi 的会话格式提供了一个有代表性的例子：文件保存完整的树形历史，压缩记录可以携带 `retainedTail`。恢复时，运行时根据当前分支和保留尾部重新构造模型需要看到的内容，而不是把整份会话文件原样交给模型。（感兴趣可以看下Pi在文件树的设计）

### 历史里记录过工具调用，重启后能再执行一次吗？

不能直接执行。假设 Agent 调用工具创建了一张工单。服务端已经创建成功，但客户端在收到响应前崩溃。此时 Session 中可能只有 Tool Call，没有对应的 Tool Result。

重启后如果直接重放这条工具调用，就可能创建第二张工单。**会话只能告诉系统“曾经发起过什么动作”，不能单独证明外部系统最终执行到了哪一步。**

要安全恢复，工具协议还需要**提供幂等键**、可查询的请求 ID 或补偿动作。系统应当先查询外部结果，确认动作没有发生后再重试，而不是仅凭会话缺少 Tool Result 就重新执行。

文件工具相对容易核对，因为修改结果通常仍保留在工作区，Checkpoint 也可能提供工作区证据。但“容易核对”仍然不等于“可以无条件重放”。恢复前依然需要重新读取文件现场。

### /resume 能从崩溃前的工具步骤继续吗？

通常不能。

Coding Agent 中常见的 `/resume` 恢复的是会话身份、历史消息和仍然存在的工作区结果，不是 Python 协程、Shell 子进程、模型流或 Agent Loop 的程序计数器。

如果系统希望在进程重启后，从某一个工具步骤精确继续，就必须额外持久化执行图、步骤输入、步骤输出、重试次数、任务租约和外部副作用标识。这已经接近持久执行（Durable Execution）或工作流引擎的设计。

因此，Coding Agent 常见的恢复过程更接近：

> 重新读取会话事实，核对当前工作区和外部结果，然后开始一个新的轮次。

它不是把旧轮次的调用栈重新复活。

<callout id="MwNgdY7xhoglVNx3eLScjJdknjg" emoji="❗">
Agent 有两个世界：它记录的表征世界，和它行动的物理世界。会话只是表征世界的账本——账本完整，只证明它没缺东西；任务可继续，却要求账本描述的现场此刻仍然成立。完整性是证据对自身的忠实，可继续性是证据对世界的有效：前者只需要检查证据自己，后者必须回到世界重新测量。而世界永远在账本之外变化 ——用户会改文件、远端会没响应、进程会崩溃——所以'证据完整'与'可以继续'之间那条路，永远无法被推导出来，只能被走过去核对一遍。
</callout>

产品可以承诺“继续同一会话”“从上次的文件状态继续”或“回退到某次用户输入前”；如果没有持久化执行图，就不应承诺“从崩溃的工具步骤精确续跑”。

会话文件可以毫无损坏，但工作区已经被用户修改；工作区可以保留修改，但会话还没有保存这一轮的意图；两者都可能存在，而外部工具的执行结果仍然未知。

恢复系统必须允许这些组合出现，因为真实故障不会替系统挑选一个干净的事务边界。

正因为 Session、Context、Workspace、进程内执行和外部副作用具有不同的持久化边界，把它们全部塞进一个存档，并不能自动得到可靠的恢复能力。我们接下来继续看这种朴素方案会在哪里失效。

## 二、把所有状态塞进一个存档，不是一个好的方案

写后端接口时，我们经常需要处理请求重试。客户端没有收到响应，不代表服务端没有执行；为了避免重复创建订单或重复扣款，系统通常会给操作分配一个稳定的幂等键，并持久化这次操作的处理状态。

沿着这个思路，一个很自然的 Agent 恢复方案是：**把一次 Turn 看成一台状态机，每完成一个步骤，就把当前进度写进 JSON。**

```JSON
{
  "turn_id": "turn_123",
  "current_step": "create_ticket",
  "status": "pending",
  "tool_request_id": "req_456"
}
```

进程重新启动后，读取这份 JSON，找到上次停下的位置，再从没有完成的步骤继续。

这里的 JSON 只是载体。把它替换成 JSONL、SQLite、Redis 或关系数据库，并不会改变这个方案的核心假设：

> 一份存档能够代表整个 Agent 在某个时刻的完整状态。

这个假设要成立，至少需要满足几个条件：

- 所有状态由同一个对象拥有；
- 所有变化可以在同一个提交边界内完成；
- 失败后能够一起回滚，或者一起重放；
- 存档中的内容就是系统真实状态的唯一来源。

普通业务对象有时可以满足这些条件。例如，订单状态和幂等键都保存在同一个数据库事务中，服务端可以在写入订单的同时记录这个请求已经处理过。

Agent 的执行过程不同。**一轮任务可能同时修改 Session、Workspace、Memory、Delivery 和外部系统**；Context 在下一次模型调用前重新组装，进程内的迭代位置、锁和流式缓冲则存在于内存中。这些状态由不同对象拥有，在不同时间提交，也采用不同的写入协议。

问题因此不在于 JSON 能不能保存足够多的字段，而在于一份本地存档没有资格替所有状态域作证。

### 本地存档和外部动作之间总有一道空窗

假设 Agent 正在调用工具创建一张工单。这个过程至少包含两个写入：

1. 远端系统创建工单；
2. 本地存档把这一步更新为 `completed`。

如果先更新本地存档，再调用远端系统：

```JSON
本地状态写入 completed
        ↓
进程崩溃
        ↓
远端工单尚未创建
```

重新启动后，本地记录显示这一步已经完成，真实世界里却没有对应的工单。

如果先调用远端系统，再更新本地存档：

```JSON
远端工单创建成功
        ↓
进程崩溃
        ↓
本地状态仍然是 pending
```

这次本地记录落后于真实世界。恢复逻辑若从 `pending` 状态重新执行工具，就可能创建第二张工单。

把两次写入靠得更近，只能缩短故障空窗，不能消除它。因为本地存储和远端工单系统不属于同一个事务。

真正的幂等需要让产生副作用的系统参与。例如，Agent 两次调用创建工单接口时，都携带同一个操作标识：

```JSON
idempotency_key = turn_123:create_ticket
```

工单系统识别这个键后，第二次请求可以直接返回第一次创建的工单，而不会再次产生副作用。本地存档负责保存幂等键、已经观察到的响应和仍然未知的结果；“只创建一次”的保证来自真正执行动作的工单系统。

如果外部系统不支持幂等键，恢复时只能通过 request ID 查询、按业务字段对账、执行补偿动作，或者把结果标记为未知并交给用户确认。

历史中缺少 Tool Result，只能说明 Agent 没有持久化到这个响应，不能证明工具没有执行。

### 即使只看本地状态，也不存在一种通用写法

把外部系统暂时放到一边，只保存 Agent 本地拥有的事实，问题仍然没有完全消失。

Session 中的正常对话不断向后增长，适合追加写入。进程在一次追加中途崩溃，通常只会影响文件末尾，此前已经写完整的记录仍然可以读取。

Undo、Clear 和 Retry 会改变当前有效历史。原来的消息可能仍然存在于存储中，但不再属于接下来要使用的历史。系统需要通过原子重写、tombstone、分支指针或新的会话副本表达这种变化，仅靠向文件末尾追加消息并不够。

多个进程同时保存同一个 Session 时，文件锁只能让写入依次发生。系统还需要版本、快照或纪元判断当前写入是否建立在最新状态上，否则一个较早取得的旧对象，仍然可能在稍后覆盖更新的历史。

Workspace 又使用另一套事实源。文件系统和 Git 可以证明当前目录里有哪些文件，却不知道模型看过哪些消息，也不知道 Tool Call 和 Tool Result 怎样配对。

反过来，Session 可以记录工具返回了“文件修改成功”，但这条消息不能证明文件仍然保持当时的内容。用户可能已经手工修改文件，另一个进程也可能覆盖结果。

Context 的生命周期更短。它是根据当前配置、Session 历史、Memory 召回、工具定义和本轮输入临时组装出来的模型工作视图。恢复 Session 后，系统需要重新构造 Context，而不是从存档中取回上一次模型请求并原样复用。

这些状态变化的方向、频率和事实来源都不同。把它们序列化成同一个对象，只是把差异藏进了更多字段，没有消除差异。

### 一次 Turn 的完成状态不是一个布尔值

单一存档通常还会诱导系统使用一个统一的 `success=true` 表示整个任务已经结束。

真实的 Agent 轮次可能留下这样的结果：

```Plain Text
Agent Loop：completed
Session：saved
Workspace：modified
Memory：failed
Delivery：dropped
外部副作用：unknown
```

这里没有一个准确的 `success=true` 或 `success=false`。

Agent Loop 已经完成，说明计算过程产生了终态；Session 已经保存，说明对话事实可以重新读取；Memory 写入失败，只影响派生知识；Delivery 失败，表示用户没有收到已经生成的回复；外部副作用为 `unknown`，则需要查询或人工确认。

恢复逻辑需要根据每个状态域的结果分别决定下一步：

- Session 已保存，从已有事实重新组装新的 Turn；
- Workspace 已修改，先读取文件现场；
- Memory 写入失败，补写派生知识；
- Delivery 失败，重新投递已有回复；
- 外部副作用未知，使用幂等键或 request ID 查询；
- 进程内执行已经消失，从最近的持久化边界重新开始。

把这些结果压进一个布尔值，会让系统无法区分重新计算、补写、重投递和人工确认。

### 存档应该保存证据，而不是假装拥有整个世界

JSON、JSONL、数据库和 Git 都可以成为可靠的持久化工具，前提是它们只为自己有资格证明的状态负责：

- Session 保存已经发生的对话事实；
- Workspace 和 Checkpoint 保存文件现场的证据；
- Memory 保存从历史中提取出的长期知识；
- Delivery 保存消息是否送达；
- 外部系统保存工单、邮件、部署等副作用的最终结果；
- Context 在新的模型调用前重新组装；
- 进程内状态随旧进程消失，新的 Turn 从持久化边界开始。

恢复系统要做的，是重新读取这些事实源，判断哪些结果已经确认、哪些结果仍然未知，再选择继续、查询、补偿或重新投递。

> 一份存档可以保存 Agent 已经知道什么，但不能单独证明整个世界发生了什么。

理解这个边界后，再比较不同Agent Harness的恢复设计，关注点就不再是谁保存的字段更多，而是它们如何划分状态所有权：怎样定位 Session，怎样表示有效历史，怎样重建 Context，是否保存 Workspace 证据，以及把哪些动作留给新的 Turn 重新判断。

## 三、优秀 Harness 怎样把中断的会话接回来

上一章留下了一个麻烦的问题：文件可能已经修改，Session 却还没来得及记录结果。

假设用户让 Agent 修复一个失败的测试。模型发出编辑工具调用，工具已经把新内容写入磁盘，进程却在保存 Tool Result 之前退出。重新启动后，系统面对的是一个不一致的现场：

```text
Session：停在 Tool Call
Workspace：文件已经改变
进程内执行：调用栈、锁和重试计数全部消失
工具结果：可能成功，但没有进入会话记录
```

这时执行 `/resume`，系统应该从哪里继续？

它不能看到缺失的 Tool Result 就直接重跑工具，因为文件可能已经改过；也不能只把旧消息重新交给模型，因为旧消息不能证明当前文件仍然处在当时的状态。恢复需要先读取已经保存的事实，再检查仍然存在的工作区，最后启动一次新的 Turn。

Pi、OpenCode 和 Claude Code 都处理了这个问题，但它们选择的重点不同。Pi 先把“沿哪段历史继续”表示清楚；OpenCode 把消息、工具过程和文件变更拆成可查询对象；Claude Code 则在会话主干之外，为文件历史、Worktree 和运行模式准备各自的恢复逻辑。

下面的分析来自这些项目的源码与文档，主线集中在六个入口：

| Harness | Git 仓库 | 源码入口 | 这一处负责什么 |
|-|-|-|-|
| Pi | [earendil-works/pi](https://github.com/earendil-works/pi) | `packages/coding-agent/src/core/session-manager.ts` | Session Entry、历史树和模型上下文 |
| Pi | [earendil-works/pi](https://github.com/earendil-works/pi) | `packages/coding-agent/docs/tree.md` | `/tree` 与 `/fork` 的用户语义 |
| OpenCode | [anomalyco/opencode](https://github.com/anomalyco/opencode) | `packages/opencode/src/session/session.ts` | Session、Message、Part 和 Fork |
| OpenCode | [anomalyco/opencode](https://github.com/anomalyco/opencode) | `packages/opencode/src/session/revert.ts` | 文件回退、撤销回退和历史清理 |
| Claude Code | 先前泄漏的cc仓库，请大家自己检索 | `src/utils/sessionStorage.ts` | Transcript、消息链和附加记录 |
| Claude Code | 先前泄漏的cc仓库，请大家自己检索 | `src/utils/sessionRestore.ts` | Resume 时各类状态的恢复 |

### Pi：先回答“从哪段历史继续”

先看一个比进程崩溃更容易观察的操作。用户与 Agent 已经讨论了两种修复办法，现在想回到较早的一条消息，改用另一种方案继续。

如果 Session 只是一段普通数组，最直接的做法是删除目标消息之后的内容，再把新消息追加到末尾。这样虽然能继续对话，刚才探索过的另一条路径却消失了。Pi 没有删除它。

Pi 把 Session 保存成 JSONL。第一行是 Session Header，记录会话 ID、格式版本、创建时间和工作目录；后面的每条 Entry 都有自己的 `id` 和 `parentId`。消息、模型切换、Compaction 和 Branch Summary 都是 Entry，它们通过父子关系组成一棵树。

```text
Session Header
└── A  user：修复这个失败的测试
    └── B  assistant：先检查 fixture
        ├── C  user：继续方案一
        │   └── D  assistant：修改 fixture
        └── E  user：改试方案二
            └── F  assistant：调整实现
```

`/tree` 做的事很小：把当前活动位置移动到选中的 Entry。旧分支仍留在原文件里，下一条新记录会挂到新的位置下面。用户因此可以在同一份 Session 中来回探索，不必先复制或截断历史。

重新打开这份 Session 时，Pi 先读取所有 Entry，再根据父子关系恢复历史树。真正进入模型窗口的内容由 `buildSessionContext()` 重新构造。它从当前 Leaf 沿 `parentId` 回到根，只取这条路径上的记录，再处理路径上最近的 Compaction 和 Branch Summary。

```text
完整 Session = 所有 Entry 组成的历史树
当前历史     = path(root, current_leaf)
模型 Context = project(当前历史, Compaction, 当前模型设置)
```

下面这张图把 Pi 的恢复路径收在一起。左边是始终保留的完整历史树，右边是模型真正收到的当前路径。

> [飞书图像未纳入仓库快照] 图 3-1：Pi 保留完整历史，只重建当前路径

Session 保存完整历史，Context 保存模型这一次需要看到的视图。Pi 做 Compaction 时，会追加一条包含摘要和 `firstKeptEntryId` 的新记录；早期消息仍在 JSONL 中，只是不再全部进入下一次模型调用。

Pi 还区分了两种“从旧位置继续”。`/tree` 在原 Session 内移动活动位置，适合保留一棵可反复探索的历史树；`/fork` 把选中路径抽取为新的 Session 文件，父子会话从此独立增长。前者改变当前分支，后者创建新的历史所有者。

回到开头的崩溃现场，Pi 能准确回答两个问题：哪些会话事实已经写入，以及下一次模型应该沿哪条历史继续。可它不会仅凭历史树把整个工作区恢复到某个 Entry。Compaction 和 Branch Summary 可以记录读过、改过哪些文件，这些记录有助于模型接续任务，却不能替文件系统作证。

这正好暴露出下一层需求：如果产品还要支持撤销文件、恢复文件，再明确的消息树也不够。

### OpenCode：消息和文件需要一起回退

OpenCode 的 Session 不是一份只包含消息文本的记录。它把数据拆成了几个可以独立查询的对象：Session 保存项目、工作目录、父会话和回退状态；Message 属于 Session；Part 再属于 Message。文本、推理、工具调用、工具结果、Patch 和 Compaction 都可以拥有自己的 Part。

```text
Session
├── Message：user
└── Message：assistant
    ├── text Part
    ├── tool Part
    └── patch Part
```

这样的拆分在普通聊天里显得有些重，到了文件回退就有了作用。用户选择一条旧消息执行 Revert 时，系统不只要隐藏后面的回答，还要找到这些回答对应的文件变更。

当前实现的主要流程是：

```text
确认 Session 没有运行
        ↓
找到目标 Message 或 Part
        ↓
收集目标之后的 Patch Part
        ↓
保存当前 Workspace Snapshot
        ↓
根据 Patch 回退文件
        ↓
把恢复点写入 Session.revert
```

第一步先检查 Session 是否忙碌，是因为执行仍在写文件时做回退，很容易得到一半来自旧 Turn、一半来自 Revert 的现场。确认可以操作以后，`revert.ts` 扫描目标位置之后的 Part，收集其中的 Patch，并让 Snapshot 服务保存当前工作区。随后文件回到旧状态，Session 中则留下 `messageID`、可选的 `partID`、Snapshot 和 Diff。

这时历史还没有被永久删除。用户执行 Unrevert，系统可以用之前保存的 Snapshot 返回回退前的工作区，并清除 `Session.revert`。只有用户接受当前恢复点并继续执行，Cleanup 才删除目标之后的 Message 或 Part。

OpenCode 的关键不在某个数据表，而在这段可撤销协议。图中的分叉发生在文件已经回退、原现场仍有 Snapshot 可以找回之后。

> [飞书图像未纳入仓库快照] 图 3-2：OpenCode 的 Revert 先保存现场，再决定提交或撤销

```text
prepare：保存当前现场
apply：回退文件并暂存恢复点
commit：继续执行后清理旧历史
rollback：Unrevert 恢复原现场
```

Fork 也体现了结构化对象的代价。OpenCode 创建一个新 Session，复制目标消息之前的历史，但不会继续复用原来的对象身份。复制过程中，Message 和 Part 都会得到新 ID；Assistant Message 的 `parentID`、Compaction Part 的尾部引用也要映射到新对象。

```text
原 Session：M1 → M2 → M3 → M4

在 M3 前分叉

新 Session：M1' → M2'
           Message、Part 和内部引用都换成新身份
```

这种 Fork 成本比移动一个 Leaf 高，却换来了明确的所有权。新旧 Session 可以独立删除、分享和继续执行，不会因为复用内部 ID 而互相污染。

数据库记录仍然不是模型请求。恢复以后，Message 和 Part 还要被转换、筛选并组装成 Provider 接受的消息。数据库负责可靠保存和查询对象，Context 层决定模型此刻看见其中哪些内容。

现在，历史路径、文件回退和对象身份都有了比较清楚的归属。但一个 Coding Agent 运行时还有模型选择、Todo、Worktree、文件备份和压缩边界。继续把这些内容塞进 Message 或 Part，数据结构会越来越臃肿。Claude Code 选择让不同状态域拥有不同的恢复逻辑。

### Claude Code：会话是一条主干，其他状态各自恢复

<callout id="LfchdJuyaoYE7AxLtGkcMuGcnmb" emoji="❗">
这一节参考 Claude Code v2.1.88 泄漏源吗
</callout>

Claude Code 以项目目录下的 JSONL Transcript 保存会话主干。消息带有 `uuid`、`parentUuid`、`sessionId` 和 `cwd`，父 UUID 把用户消息、助手消息和工具结果连接成可以追溯的链。Transcript 中还会追加文件历史快照、Worktree 状态、Context Collapse 记录等专用 Entry。

Claude Code 把 Resume 拆成一组恢复步骤。系统先加载会话记录，随后由不同恢复逻辑处理各自拥有的状态。以 `sessionRestore.ts` 为例，恢复过程会分别处理消息、文件历史、Todo、Agent 设置、Context Collapse 和 Worktree。

```text
加载 Transcript
      ↓
恢复消息链与会话身份
      ↓
恢复 File History、Todo、Mode 等附加状态
      ↓
重新检查 Worktree 和当前目录
      ↓
根据当前配置组装 Context
      ↓
启动新的 Turn
```

这张图里，消息链只是恢复的主干。File History、Todo/Mode 和 Worktree 分别从持久化记录中恢复，其中 Worktree 还要回到文件系统重新验证目录。

> [飞书图像未纳入仓库快照] 图 3-3：Claude Code 为不同状态域分别恢复，并重新验证 Worktree

Worktree 恢复能很好地说明“重新检查”为什么不可省略。Transcript 可以记录上次退出时所在的 Worktree 路径，但用户可能已经删除目录。Resume 不会只相信旧路径；它会尝试切换目录。切换失败时，恢复逻辑清掉陈旧的 Worktree 状态，留在当前可用现场。记录告诉系统上一次知道什么，文件系统告诉系统现在还剩什么。

文件历史也没有直接塞进普通消息。编辑发生时，文件备份由 File History 负责保存，Snapshot 元数据则作为专用记录进入 Transcript。Resume 恢复 Snapshot 索引，Rewind 再根据消息与 Snapshot 的关联处理文件。Transcript 保存的是关联关系，文件内容由自己的存储负责。

Compaction 带来的是另一类恢复问题。摘要已经替代一部分旧内容进入模型窗口，但磁盘上仍可能保留压缩前消息和被保留的尾部。加载器需要根据 Compact Boundary、Parent UUID 和保留段把有效链重新接起来。

源码中的处理很保守：如果保留段的 `tail → head` 链能够完整验证，就重新连接端点并裁掉已被摘要替代的前缀；如果中间 UUID 缺失，验证无法完成，加载器会放弃这次裁剪，让更多旧历史进入恢复结果。恢复可能因此更重，但不会在证据不足时静默拼出一条错误会话。

普通 Resume 与 Fork Session 也有不同的所有权。前者继续使用原 Session ID，并向原 Transcript 追加；后者使用新的 Session ID，把选中的历史与后续恢复所需记录迁移到新会话。只复制屏幕上的消息文本，会遗漏文件历史和内容替换等旁路状态。

Claude Code 的复杂度来自它想恢复更多产品状态。增加一种持久化状态，通常也意味着增加对应的写入记录、加载逻辑、兼容处理和失效校验。覆盖范围越大，恢复协调成本越高。

### 三套实现其实在回答五个问题

现在再回头看开头的崩溃现场的例子：Session 停在 Tool Call，文件已经改变，旧进程已经消失。Pi、OpenCode 和 Claude Code 使用了不同的数据结构，却都必须回答五个问题。

1. 哪些事实已经可靠写入？
2. 接下来沿哪段历史继续？
3. 这一次模型应该看到什么？
4. 文件现场现在是什么？
5. 系统应该继续、分叉、回退，还是先查询未知结果？

在架构设计中，可以给这五项职责加上名字。它们从“恢复一次任务”向下拆分不同的状态责任，最后共同收敛到一次新的 Turn。

**Durable Journal** 负责判断提交边界。用户输入、Assistant Message、Tool Call 和 Tool Result 是否已经保存，都要有可检查的记录。

**History Topology** 负责表示历史之间的关系。Pi 使用 Entry Tree 和当前 Leaf；OpenCode 在 Fork 时复制历史前缀并重映射对象；Claude Code 使用 Parent UUID 连接消息链。

**Context Projection** 负责生成下一次模型调用。完整历史可能远大于模型窗口，系统指令、模型和工具定义也可能已经变化，所以每次恢复都要基于当前配置重新投影。

**Workspace Evidence** 负责文件现场。Pi 主要保留文件活动线索；OpenCode 把 Patch 与 Snapshot 纳入 Revert；Claude Code 维护与消息关联的 File History。三者覆盖范围不同，但都没有让普通消息文本单独为文件内容作证。

**Recovery Policy** 负责决定动作。Resume 沿既有会话启动新 Turn；Fork 创建新的历史所有者；Rewind 或 Revert 同时移动历史边界和文件现场；外部副作用仍然未知时，系统还需要查询、对账或交给用户确认。

把三套方案放在一起，可以得到一张以用户操作为入口的对照表：

| 用户想做什么 | Pi | OpenCode | Claude Code |
|-|-|-|-|
| 继续上次会话 | 读取 Entry Tree，重建当前路径的 Context | 读取 Session、Message 和 Part，再生成模型消息 | 加载 Transcript，并恢复相关状态域 |
| 回到旧消息探索 | 在同一 Session 中移动 Leaf，旧分支仍保留 | 通常通过 Fork 创建独立 Session | 通过恢复或分叉后的新会话继续 |
| 创建独立分支 | 抽取路径为新 Session 文件 | 复制历史前缀并重映射 Message、Part 引用 | 使用新 Session ID 迁移所需历史与附加状态 |
| 回退文件 | 不提供通用的节点级工作区回退 | Patch、Snapshot 与暂存 Revert 联动 | Message 与 File History Snapshot 关联 |
| 历史过长 | 追加 Compaction Entry，旧历史仍保留 | Compaction Part 参与后续模型投影 | Compact Boundary 与消息链共同恢复有效上下文 |

选择哪种结构，取决于产品准备承担什么保证。Pi 优先保持历史模型小而透明；OpenCode 为可查询、可撤销的操作付出对象复制和快照协调成本；Claude Code 恢复的状态域更多，相应地也需要更多 Restore Handler 和兼容逻辑。它们没有共享一套标准存储结构，共享的是清楚的状态所有权。

### 带着这五个问题读 Pico

第三方实现为 Pico 提供了一组已经被真实产品验证过的设计选择。Pico 仍要结合自己的存储方式、运行时边界和产品目标作出取舍。

下一章阅读 Pico 时，我们可以沿着这五个问题寻找证据：Session 写在哪里，写到哪一步才算提交；有效历史怎样确定；模型输入怎样从历史重新组装；Workspace 由谁保存和校验；遇到中断、回退或未知副作用时，系统依据什么决定下一步。

这样再看到 `resume`、`fork`、Checkpoint 或文件锁，就不会只停在“项目支持这个功能”。我们可以继续追问：它保证了什么，依赖哪个事实源，又把哪些风险留给新的 Turn 处理。

## 四、Pico 怎样定义一次安全的恢复

前三章已经得到一个行业层面的结论：恢复不是把旧 Agent 从磁盘里复活，而是找回可信事实，重新确认现实，再决定下一步。现在轮到 Pico 作出自己的选择。

仍然从那个不完整的现场开始。模型已经发出工具调用，文件可能已经改变，Tool Result 却没有可靠进入 Session；旧进程的调用栈、锁和重试计数已经消失，远端系统是否收到请求也无法只靠本地判断。

如果把“恢复成功”定义成回到崩溃前一毫秒，系统就必须同时控制 Session 文件、工作区、进程内存和所有外部系统。这个前提在真实 Agent 中并不成立。Pico 因而采用一个更保守、也更可验证的定义：

<callout id="doxcnJjf9YQLmYIo2gQcUc7Xe2M" emoji="💡">
**一次安全的恢复，是验证已经保存的事实，重新观察当前现场，并用这些证据启动新的 Turn。**
</callout>

```text
安全恢复
= 已保存事实可信
+ 当前现场重新测量
+ 下一步动作不会盲目重复副作用
```

### 恢复的对象不是旧进程，而是下一次决策所需的证据

这个定义把恢复拆成五个连续动作：

1. **Locate**：确定恢复的是哪个 Workspace 下的哪个 Session。
2. **Validate**：验证 Session 的身份、完整性和写入代际。
3. **Observe**：重新读取当前文件现场，必要时查询外部系统。
4. **Project**：根据当前模型、工具和配置重新组装 Context。
5. **Decide**：决定继续、分叉、回退、查询，还是停下来确认。

五个动作最后都收敛到一个新的 Turn。Pico 不保存旧 Python 调用栈，也不会把历史 Tool Call 当作待执行队列。

> [飞书图像未纳入仓库快照] 图 4-1：Pico 的证据驱动恢复模型

### 这套模型有两条管线和一组横切保护

| 部分 | 负责什么 | 不负责什么 |
|-|-|-|
| 写入管线 | 把一次 Turn 中可复用的语义事实写入 Session，再触发派生处理 | 不把所有运行时细节都永久保存 |
| 恢复管线 | 定位并验证 Session，重新观察 Workspace，投影 Context，启动新 Turn | 不还原旧进程，不自动重放工具 |
| 一致性保护 | 用身份校验、文件锁、Epoch 和内容快照保证证据可信 | 不把多个状态域变成一个全局事务 |

对应到 Pico 当前实现，可以得到六个稳定职责。实现类和存储介质以后可以变化，但这些问题不会消失。

| 抽象职责 | 回答的问题 | Pico 当前选择 |
|-|-|-|
| Session Identity | 恢复的是谁 | Workspace State Root、Session Key、唯一 ID 解析 |
| Durable Journal | 哪些事实已经可靠发生 | 每会话一份 JSONL，正常增长追加，结构变化重写 |
| Context Projection | 模型这一次应该看到什么 | Context Engine 按当前配置选择和组装历史 |
| Workspace Evidence | 文件现场现在是什么 | 当前文件系统，加上尽力而为的 Shadow Git Checkpoint |
| Recovery Policy | 下一步应该做什么 | Resume、Fork、Undo、Retry 与错误分类 |
| Consistency Fences | 证据是否仍然可信 | 身份校验、完整性检查、Lock、Epoch、内容快照 |

### Pico 承诺什么，又明确放弃什么

| 状态域 | Pico 恢复时怎么处理 | 明确不承诺什么 |
|-|-|-|
| Session 事实 | 校验身份与完整性后重新加载 | 不恢复旧进程对象 |
| 模型 Context | 根据当前配置重新组装 | 不复用上一次请求体 |
| Workspace | 读取当前文件，并参考可用的 Checkpoint 证据 | 不保证自动回到某条消息时的文件状态 |
| Tool Call | 作为历史事实提供给模型 | 不自动再次执行 |
| 外部副作用 | 依赖查询、对账或幂等协议 | 不提供 exactly-once |
| 进程内执行 | 丢弃并启动新 Turn | 不从旧调用栈继续 |

这些边界背后有一组稳定的优先级：

```text
事实完整性 > 自动继续
明确失败 > 猜测修复
状态分域 > 超级存档
启动新 Turn > 重放旧动作
本地透明性 > 引入不必要的重型基础设施
```

这不是说自动化不重要，而是说恢复自动化只能建立在可信证据之上。下面先沿着用户真正执行的一次 `pico run --resume`，看这套模型怎样落到一条完整路径。

## 五、一次 /resume 怎样启动新的 Turn

假设用户昨天在 CLI 中让 Pico 修复一个失败测试，今天重新进入同一个项目，希望继续讨论。真正开始交互的入口是：

```bash
pico run --resume 20260815_103200_a1b2c3
```

<callout id="doxcnAsDLPYZJMeOZrsKQAQd6Md" emoji="📌">
`pico sessions resume ID` 只负责解析 ID 并输出完整 Session Key；真正加载会话并进入 Agent 的是 `pico run --resume ID`。
</callout>

### 只给一个 ID，为什么还不足以找到会话

Session 不是全局漂浮的聊天记录。相同的短 ID 可能来自不同 Channel，不同 Workspace 也拥有各自的状态根。恢复必须先回答两个问题：当前操作的是哪个项目，这个项目状态目录中的哪份会话属于用户。

```text
Workspace
  ↓
Workspace State Root
  ↓
sessions/<channel>/<chat_id>.jsonl
```

内部身份使用 `channel:chat_id`。Channel 防止 CLI、TUI 或其他入口碰巧产生相同短 ID 时落到同一文件；Workspace State Root 则把不同项目的 Session 隔开。会话键解决“是谁”，状态根解决“到哪里找”，两者不能合成一个模糊的全局目录。

解析时，完整 Session Key 可以直接使用；裸 ID 先尝试精确匹配，再尝试唯一前缀。出现多个候选时必须明确失败，而不是选择最近使用或列表中的第一项。恢复失败会中断一次操作，恢复到错误项目却可能让模型读取错误历史并修改错误文件。

### 加载 Session 不是把文件读成一个 Python 对象就结束

找到文件以后，加载器仍要检查证据是否可信：

- 元数据中的 Session Key 是否与请求身份一致；
- 同一文件中的多条 Metadata Record 是否保持同一身份；
- 文件路径推导出的 Channel 与 Chat ID 是否匹配；
- JSONL 是否只在可解释的最终尾部出现残缺；
- 写入代际是否完整，当前文件是否属于预期的一代。

如果这些检查失败，安全结果不是创建一份空会话继续。那会把“历史损坏”伪装成“用户从未聊过”，后续模型会在错误前提上生成新的事实。Pico 选择暴露存储损坏，让调用方决定修复、恢复备份或停止操作。

### 完整 Session 与模型这一次看到的 Context 不是同一个东西

Session 加载成功后，Pico 获得的是完整事实来源。模型请求仍需根据当前运行环境重新构造。

```text
完整 Session
+ 当前 System Instruction
+ 当前 Tool Definitions
+ 当前 Skills
+ 当前 Memory Recall
+ 当前 Token Budget
  ↓
Context Projection
  ↓
本次 Provider Request
```

短会话可以直接进入快速路径；历史产生压力时，Context Engine 会保护关键消息，并选择相关、近期或已经归档的内容。无论走哪条路径，Session 都没有因为 Context 变短而丢失原始事实。

这也是为什么切换模型、调整工具或修改系统指令之后仍然可以 Resume。恢复复用的是 Session 事实，不是旧模型请求的序列化副本。

### 恢复的最后一步是启动新 Turn

完成身份解析、完整性检查和 Context 投影以后，Pico 才把用户的新输入交给 Agent Loop。此时工作区来自当前文件系统，工具定义来自当前 Runtime，模型面对的是“过去事实加当前现场”。

> [飞书图像未纳入仓库快照] 图 5-1：一次 /resume 从 Session 证据走向新的 Turn

历史里的 Tool Call 和 Tool Result 只告诉模型过去发生了什么。只有新的模型响应再次产生 Tool Call，Tool Runtime 才会执行动作。因此 Resume 不会因为看见历史工具调用就重新编辑文件、重新发邮件或重新创建工单。

到这里，恢复读取路径已经走通。它成立的前提是磁盘 Session 真的是一份可信账本。下一章从写入模式出发，推导这份账本为什么采用 JSONL，以及为什么 Pico 同时需要追加和重写两条路径。

## 六、Session 事实怎样跨过崩溃边界

选择存储结构之前，先观察 Session 的真实变化。绝大多数 Turn 不会修改十轮以前的消息，只会在现有历史尾部增加新的 User Message、Assistant Message、Tool Call 和 Tool Result。

```text
下一次持久化状态
= 已经保存的历史前缀
+ 本轮新增的语义消息
```

如果每轮都把完整历史重新写一遍，写入成本和故障窗口会随会话长度增加；如果只在进程退出时保存，崩溃窗口又会覆盖整个运行期；如果直接引入数据库，事务和索引会更强，但本地 Agent 也会增加运行依赖，并失去直接查看、复制和诊断会话文件的简单性。

Pico 选择每个 Session 一份 JSONL，以追加处理正常增长，只有历史结构变化时才执行原子重写。这不是“文件比数据库先进”，而是当前写入形态、产品规模和本地透明性共同决定的取舍。

### 为什么可变 Metadata 也采用追加

JSONL 中主要有两类记录：Metadata Record 和 Message Record。消息沿文件顺序组成历史；标题、更新时间、固化水位线和待澄清状态会变化，因此每次保存追加一条更新后的 Metadata Record，加载时以最后一条有效记录为准。

```json
{"_type":"metadata","key":"cli:...","last_consolidated":0}
{"role":"user","content":"修复这个失败的测试"}
{"role":"assistant","tool_calls":[...]}
{"role":"tool","tool_call_id":"call_1","content":"..."}
{"_type":"metadata","key":"cli:...","last_consolidated":0}
```

这样做会产生重复 Metadata，却守住一个更重要的性质：正常保存不需要回头覆盖旧字节。历史前缀稳定，有利于崩溃恢复，也有利于 Provider 对稳定前缀进行缓存。

### 为什么正常增长走追加，结构变化走重写

保存前，系统比较内存中的消息与上次持久化快照：

```text
磁盘消息仍是内存消息的完整前缀？
  是 → 只追加新的 Metadata 与 Message
  否 → 写临时文件并原子替换
```

> [飞书图像未纳入仓库快照] 图 6-1：Pico 根据历史前缀选择追加或重写

必须比较内容前缀，不能只比较消息数量。撤销两轮再补两轮，数量可以完全相同；原地修改一条消息，数量甚至不会变化。若只看长度，系统会把新的尾部追加到旧历史后面，产生一份内存中从未存在过的组合。

Undo、Clear、历史规范化和尾部修复都会改变已经保存的结构，因此需要完整重写。原子替换保证其他读者看到旧版本或新版本，不会看到一份已经换入一半的主文件；它并不把 Session、Workspace 和外部系统变成一个共同事务。

### 写入 Session 之前，先区分事实和运行脚手架

Agent Loop 为一次技术性重试可能插入“继续回答”或思考预填消息，这些内容服务于当前模型协议，不代表用户意图。Pico 在保存前移除带恢复标记的 Synthetic Message，跳过没有文本和 Tool Call 的空 Assistant Message，对超长 Tool Result 截断，并清理运行时前缀与内嵌数据图片。

这里守住的是 Durable Journal 的语义边界：

<callout id="doxcnCt9gg55Z6vkhuWhxMLouRc" emoji="💡">
Session 应当忠实保存用户、模型与工具之间可解释的交换，不应把一次内部重试的临时提示伪装成历史事实。
</callout>

### 为什么只修复最后一条没有写完的记录

追加文件给恢复策略提供了一个可以从物理位置推导出的边界：

```text
最终一行残缺且文件没有换行
→ 可以解释为一次追加在中途崩溃

中间记录损坏，后面还有完整记录
→ 不能由一次未完成的尾部写入解释
```

前一种情况可以保留此前完整记录，并要求下一次保存通过重写清理残尾；后一种情况必须抛出 `StorageCorruptionError`。如果跳过中段坏记录继续，丢失的可能恰好是用户纠正、Tool Call 或 Tool Result，后续历史虽然仍能解析，因果链却已经被改写。

Pico 选择的不是“尽可能多读”，而是“只修复有充分物理证据的损坏”。这牺牲了一部分可用性，换取不会静默伪造历史。

### JSONL 方案买到了什么，又承担什么

| 选择 | 得到什么 | 付出什么 |
|-|-|-|
| 本地 JSONL | 可直接查看、复制、诊断，没有额外服务 | 查询和跨实体事务能力弱 |
| 正常增长追加 | 成本与新增量相关，崩溃通常只影响尾部 | 需要维护持久化快照和追加基线 |
| 结构变化重写 | Undo、Clear 等操作可以得到自洽文件 | 必须处理并发重写和陈旧写者 |
| 中段损坏 Fail Closed | 不静默生成错误历史 | 无法自动跳过所有坏记录继续使用 |

追加和原子替换只能保护一次文件更新。它们仍然不能证明写入者拿到的是最新 Session，也不能阻止一个旧进程在 Session 删除后把文件重新创建。下一章继续推导为什么有文件锁还不够。

## 七、为什么有文件锁仍然不够

两个进程同时写同一个文件，最直觉的答案是加锁。但锁只解决“这一刻谁能进入临界区”，不解决写入者在进入之前拿到的状态是否仍然有效。

考虑三个现场：

1. 进程 A 与进程 B 都从同一历史开始，各自增加一轮消息。
2. 进程 B 删除 Session，进程 A 仍持有删除前加载的对象。
3. 进程 A 准备 Undo，进程 B 已经向同一 Session 追加了两轮。

文件锁只能让这些写入排队。如果迟到的写者仍被允许基于旧视图保存，排队后的结果依然可能错误。

### 互斥、身份和新鲜度是三个不同问题

> [飞书图像未纳入仓库快照] 图 7-1：文件锁、Epoch 与内容快照分别保护不同问题

**File Lock** 负责互斥。它让读取、校验和写入处于同一个临界区，防止字节交错，也避免两个写者同时替换主文件。

**Epoch Fence** 负责逻辑身份。删除或完整重写会推进代际；一个在旧 Epoch 中加载的 Session 再次保存时，会因为“你写的已经不是这一代”而被拒绝。这阻止了删除后复活，也阻止了相同 Key 删除重建后的 ABA 污染。

**Content Fence** 负责状态新鲜度。追加前重新比较 Metadata、固化水位线和待澄清状态；重写前还要比较完整消息快照。另一个写者已经改变基线时，本次操作失败，而不是把新历史覆盖掉。

```text
Lock：现在是不是只有我在写？
Epoch：我写的是不是这一代？
Content Fence：这一代在我读取后有没有变化？
```

### 为什么 Epoch 之外还需要 Known Marker

如果代际文件不存在，系统不能立刻把它解释为全新 Session。它还可能表示这个路径曾经存在，但代际证据自己损坏或丢失。Pico 额外保存 Known Marker，用来区分“从未存在”和“存在过但 Epoch 不见了”。

后者必须 Fail Closed。否则一个旧写者只要等到 Epoch 文件丢失，就会重新以第零代身份写入，恰好绕过原本用来防止复活的栅栏。

### 生命周期操作是不同的状态变换

**Fork** 选择 fork-at-head 全量深拷贝。子 Session 使用新 Key，复制完整消息，保存父会话血缘，继承固化水位线，并清除不应跨会话延续的待澄清状态。父子随后独立追加、删除和导出。

相较 Pi 的 Entry Tree，这种方案不会在一个 Session 内保存多个活动分支，也需要付出随历史增长的复制成本；换来的好处是父子所有权简单，新旧会话不共享内部对象身份，删除和导出都可以独立完成。Pico 当前优先选择实现透明和生命周期隔离，而不是任意历史节点导航。

**Undo** 按用户消息边界裁剪未固化尾部，不允许跨越已经被 Context 或历史整理逻辑确认的固化水位线。修改后必须走带完整内容校验的 Rewrite。

**Delete** 不只是移除 JSONL。它还推进代际并清理缓存，使删除前获得的句柄不能在稍后保存时让文件复活。删除 Session 也不意味着删除 Memory、Trace 或其他状态域，它们有独立所有权。

**Export** 同时保存机器可读 Payload、人类可读 Markdown Transcript、消息数量和对规范化 Payload 计算出的 SHA-256。源 Session 删除后，导出仍能独立校验。摘要证明的是导出内容没有变化，不证明其中每个外部动作真的成功。

### 相同原则为什么还要延伸到 TUI

后端 Session 完全正确，界面仍可能把旧回复显示到新会话。切换期间，旧 Chat Stream 可能还在返回数据，用户也可能提交新输入。Pico 把切换过程串行化，切换中的提交进入等待，并用界面 Epoch 判断异步结果是否仍属于当前绑定。

磁盘 Epoch 保护“这个 Key 还是不是这一代”，界面 Epoch 保护“这个异步结果还属不属于当前页面”。二者解决的是同一种陈旧结果问题，只是边界不同。

### 应用层栅栏是本地透明性的代价

| 选择 | 获得的保证 | 代价 |
|-|-|-|
| 文件锁 | 跨进程读写互斥 | 不能单独识别陈旧身份 |
| Epoch 与 Known Marker | 删除、重建和代际缺失时拒绝旧写者 | 增加侧车状态和异常处理 |
| 内容快照校验 | 防止旧视图覆盖新历史 | 写入前需要重新读取和比较 |
| 全量 Fork | 父子拥有清楚、生命周期独立 | 时间与空间成本随历史增长 |

这些机制把 Session 账本本身保护起来，但 Agent 的任务结果还存在于工作区、Memory 和渠道中。下一章进入最容易被误解的边界：Session 已经保存，不等于整个任务已经恢复。

## 八、Session 已保存，为什么任务仍可能没有恢复

Session、Workspace、Memory 和 Delivery 各自有独立事实源，也各自可能失败。Pico 没有用一个 `completed=true` 掩盖这些中间状态，而是通过执行顺序让已经发生的事实尽可能先稳定下来。

在常规返回路径中，一次 Turn 的关键切点可以简化为：

```text
Tool 修改 Workspace
  ↓
Agent Loop 得到 Outcome
  ↓
尽力创建 Workspace Checkpoint
  ↓
规范化并保存 Session
  ↓
Context after_turn / Memory Store
  ↓
主回复进入 Delivery
```

这条顺序不是跨系统事务。它的价值在于故障发生后可以判断哪些状态已经越过自己的提交边界。

> [飞书图像未纳入仓库快照] 图 8-1：不同故障切点留下不同证据，也需要不同补救

### Checkpoint 为什么只是一层 Workspace Evidence

Pico 使用独立 Shadow Git 对工作区做每 Turn 快照。它指向真实 Worktree，却不修改用户仓库的 `.git`；默认排除 Pico 自身状态、构建产物、虚拟环境、常见凭据和日志，同时尊重工作区自己的 `.gitignore`。

Checkpoint 能回答“这一轮结束时有哪些文件变化被快照捕获”，却不能回答：

- 每个变化具体由哪一个 Tool Call 产生；
- 某个外部 API 是否成功；
- Session 是否已经保存完整语义；
- 崩溃瞬间正在执行到哪一行代码。

它是工作区撤销与审计安全网，不是完整 Crash Recovery。

### 为什么 Checkpoint 采用尽力而为

如果每个 Turn 都必须成功创建 Git Commit，没有 Git、权限不足、文件过多、磁盘故障或子进程超时都会让原本可以完成的对话失败。若完全不保存工作区证据，崩溃后又只能从当前文件现场猜测哪些修改来自 Agent。

Pico 选择中间位置：Checkpoint 增强恢复证据，但不能成为 Runtime 可用性的单点依赖。Git 命令失败时记录并降级为空结果，主 Turn 继续。默认策略只在交互式运行中启用，单次 `-m` 没有自然的下一轮，通常不支付这份成本；用户仍可选择 Always 或 Never。

### 为什么 interrupted 与 error 不使用同一恢复提示

`interrupted` 表示系统知道本轮因为迭代预算结束，可以生成部分总结，并提醒下一 Turn 检查已经改变的文件。`error` 可能来自 Provider、工具或存储失败，已经发生的动作范围不确定，盲目提示模型沿原轨迹继续可能重复危险动作。

当前 `interrupted` 恢复提示保存在 AgentLoop 内存中，只在同一实例的下一次正常用户输入中消费一次。完整进程重启后，它不会仅凭 Session 自动重建。跨进程仍然存在的是 Session 和可能成功创建的 Checkpoint，这个边界必须明确写出。

### 三个名字里都有 Recovery，解决的却不是同一个问题

| 机制 | 处理的问题 | 生命周期 |
|-|-|-|
| Empty-Response Recovery | 模型在当前 Turn 返回空内容 | 仅当前 Agent Loop |
| Interrupted-Turn Recovery | 同一进程内下一 Turn 继续部分工作 | 当前 AgentLoop 实例 |
| Session Recovery | 跨进程重新加载事实并启动新 Turn | 持久 Session |

Empty-Response Recovery 使用 Prefill、Nudge 或 Retry 修复模型协议，并在持久化前删除合成脚手架。它提高的是当前 Turn 的完成率，不是 Session 的跨进程恢复能力。

### 故障切点决定安全补救

| 故障发生在哪里 | 仍然存在的证据 | 安全动作 |
|-|-|-|
| Tool 已改文件，Checkpoint 未创建 | 当前 Workspace | 检查文件和 Git Diff，不假设修改完整 |
| Checkpoint 已创建，Session 未保存 | Workspace Snapshot | 把现场视为未确认，不伪造完整语义 |
| Session 已保存，Memory Store 失败 | Session 事实 | 补偿派生知识，不重跑工具 |
| Session 已保存，主回复投递失败 | 计算结果与 Session | 重投递或显示未投递，不重新计算 |
| 外部 API 可能成功，Tool Result 丢失 | 本地状态不完整 | 查询、对账或使用相同幂等键 |

Session 保存发生在 Memory Backend Store 之前。后者失败时，异常会继续向上暴露，但已写入的 Session 不会因此回滚。这是部分成功，不是矛盾：Session 是事实账本，Memory 是从事实派生的长期知识。

主回复的常规 Delivery 发生在 Agent Loop 返回之后，因此投递失败同样不能反推计算未发生。需要注意，Agent 在 Turn 内主动使用消息工具本身也可能造成外部副作用，这类动作应由工具协议提供查询或幂等能力。

<callout id="doxcnV52xEyqrJzvFR7s2VWcAIh" emoji="❗">
会话恢复只能重新获得本地证据，不能把一个跨文件系统、模型 Provider 和外部 API 的 Turn 变成 exactly-once 事务。
</callout>

到这里，Pico 的恢复契约、读取管线、写入管线、一致性保护和跨状态域边界已经闭合。最后还差一件事：把每条“应该如此”变成可以重复执行的故障实验。

## 九、把恢复保证变成故障实验

Session 与恢复的价值主要出现在异常路径。只运行一次成功的 `/resume`，只能证明命令在理想现场可用，无法证明写到一半、两个进程竞争或派生状态失败时不会伪造历史。

验证应当从设计承诺反推，而不是看到一个测试文件就逐个解释函数。

### 每项实验只证明一条边界

| 要证明的保证 | 故障注入 | 预期结果 |
|-|-|-|
| 只修复可证明的崩溃尾部 | 末尾追加半条 JSON，再把损坏放到中段 | 前者恢复并清理，后者明确失败 |
| 并发写入不能静默丢历史 | 两个独立写者从相同基线追加 | 完整 Turn 都保留，或陈旧写者明确失败 |
| 删除后旧句柄不能复活 Session | 一个进程删除，另一个迟到保存 | Epoch 拒绝旧写入 |
| 相同 Key 的新旧代际不能串线 | Delete、Recreate、旧写者追加 | 新 Session 保持纯净 |
| Fork 后父子独立 | 子会话追加，再删除父会话 | 子会话内容和导出仍可使用 |
| Checkpoint 不是强依赖 | 让 Git 命令失败或超时 | Checkpoint 降级，主 Turn 继续 |
| Session 与派生状态允许部分成功 | Session 保存后让 Memory Store 失败 | 异常可见，Session 事实仍在 |
| 历史 Tool Call 不是待执行任务 | 恢复含 Tool Call 的 Session | 只有新模型请求的 Tool Call 执行 |

### 实验应该从可解释的小故障逐步升级

```text
单文件尾部损坏
  ↓
单进程陈旧对象
  ↓
双进程并发
  ↓
删除与重建
  ↓
跨状态域部分成功
  ↓
真实 Resume 与外部副作用
```

前四组实验主要验证 Session Journal 与 Consistency Fences；后两组验证状态分域和 Recovery Policy。每次实验都应记录 Session 文件、Epoch、Workspace、异常类型和实际执行次数，不能只看 CLI 最终输出。

### 已有证据、待补证据和未来能力要分开写

当前测试已经覆盖尾部修复、中段损坏、并发追加、历史重写冲突、删除后复活、Key 复用、Fork 隔离、Portable Export 和 Checkpoint 降级等边界。教材可以引用测试名帮助读者定位证据，但不能用测试数量代替设计解释。

“恢复含 Tool Call 的 Session 不会自动执行工具”“Delivery 失败不重新计算”“Memory 失败形成部分成功”等结论，还应分别标注它们来自执行协议、源码顺序，还是已经存在独立的故障注入测试。没有独立测试时，应写成可验证的实现边界或建议实验，而不是升级成已经证明的产品保证。

如果未来要做到工具步骤级的自动恢复，现有 Session Transcript 和每 Turn Checkpoint 仍不够。系统还需要 Durable Turn Journal、Tool Effect Receipt、外部请求幂等键、持久化 Recovery Plan，以及更细的任务结果与投递状态。这里描述的是演进方向，不是 Pico 当前已经具备的能力。

### 读完后应该能够复述 Pico 的方案

<callout id="doxcnc4TCD1kYYlfdnOJ7tlxGXg" emoji="🎯">
Pico 将 Session 定义为跨进程事实账本，采用追加式 JSONL 与结构变化原子重写；通过文件锁、Epoch 和内容快照抵御并发与陈旧写入；恢复时重新投影 Context 并启动新 Turn，不重放历史工具；Workspace Checkpoint 作为独立、尽力而为的证据层，在运行可用性、事实完整性和恢复能力之间取得平衡。
</callout>

更短的一句话是：

> Session 保存过去发生了什么，Context 决定模型现在看见什么，Checkpoint 提供文件证据，Recovery Policy 决定下一步做什么。

## 参考资料

- [Pico CLI Agent Commands](https://github.com/Hackerismydream/pico/blob/main/pico/cli/agent_commands.py)：`--session`、`--continue` 与 `--resume` 的入口语义。
- [Pico Session Manager](https://github.com/Hackerismydream/pico/blob/main/pico/session/manager.py)：JSONL、身份校验、追加与重写、Epoch、Fork、Undo 与 Delete。
- [Pico Portable Session Export](https://github.com/Hackerismydream/pico/blob/main/pico/session/export.py)：机器载荷、Markdown Transcript 与 SHA-256 校验。
- [Pico Agent Loop](https://github.com/Hackerismydream/pico/blob/main/pico/agent/loop/main.py)：Checkpoint、Session Save、Context after_turn 与 Memory Store 的执行顺序。
- [Pico Checkpoint Service](https://github.com/Hackerismydream/pico/blob/main/pico/agent/loop/checkpoint.py)：Shadow Git、排除策略、超时与尽力而为语义。
- [Pico Empty-Response Recovery](https://github.com/Hackerismydream/pico/blob/main/pico/agent/loop/recovery.py)：PREFILL、NUDGE 与 RETRY 的单 Turn 边界。
- [State, Context, Memory, and Skills](https://github.com/Hackerismydream/pico/blob/main/docs/architecture/state-and-intelligence.md)：Session、Context、Memory 与其他状态域的所有权。
- [Session Manager Tests](https://github.com/Hackerismydream/pico/blob/main/tests/test_session_manager.py)：损坏、并发、代际、生命周期与 Fork 证据。
