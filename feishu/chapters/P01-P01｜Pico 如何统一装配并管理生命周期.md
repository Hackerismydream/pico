# P01｜Pico 如何统一装配并管理生命周期

<callout emoji="📌">
**拿到pico代码后，很直观的我们会问：**当你从 CLI、TUI 或 Gateway 启动 Pico 时，消息到来之前，谁把模型、工具、会话、记忆和后台资源接成一套能工作的 Runtime？
答案不是某个入口各自“拼一遍”，而是三个入口共同调用 `assemble_runtime()`，先得到同一种 `RuntimeAssembly`；入口只负责自己特有的外壳和后台服务。
</callout>

## 三个入口，为什么不能各装一套 Runtime

Pico 有三个常用入口。CLI 适合执行一次性任务，TUI 提供持续交互界面，Gateway 则把飞书等 Channel、Cron 和健康检查一起启动。它们面对用户的方式不同，但最终都要使用同一组核心能力：AgentLoop、SessionManager、MemoryBackend，以及由插件贡献的工具。

这里先把一个容易陌生的词说清楚。**装配（assembly）**不是一个新概念，它只是“把已经存在的部件按正确配置创建出来，并把它们接到一起”。如果三个入口各写一套装配逻辑，同一份配置就可能得到三种行为：CLI 能加载某个工具，Gateway 却忘了；TUI 能恢复会话，CLI 又用了另一套状态目录。

因此，Pico 把职责分成两层：

| 层 | 负责什么 |
|-|-|
| **Host** | CLI、TUI、Gateway 这些程序入口。负责解析参数、创建界面或 Channel，并决定何时开始接收输入。 |
| **Runtime 装配** | 读取统一配置，解析路径，加载插件能力，创建 AgentLoop、SessionManager 和 MemoryBackend，并把结果作为一个整体返回。 |

## 先看六个源码位置

阅读这一篇时，不需要把整个仓库铺开。先围绕一次 `assemble_runtime()` 调用，跟住下面六个位置即可：

| 源码位置 | 阅读时看什么 |
|-|-|
| `pico/cli/runtime.py` | `RuntimeAssembly` 和 `assemble_runtime()`：统一装配的主体。 |
| `pico/cli/gateway_commands.py` | Gateway 如何调用装配、启动后台服务，以及按顺序关闭资源。 |
| `pico/cli/agent_commands.py` | CLI 入口怎样复用同一套 Runtime。 |
| `pico/cli/tui_commands.py` | TUI 入口怎样复用同一套 Runtime。 |
| `pico/agent/loop.py` | AgentLoop 如何接收模型、工具和会话能力。 |
| `pico/session/manager.py` | 会话记录在哪里创建、恢复和持久化。 |

<callout emoji="💡">
推荐的读法：先从一个入口找到 `assemble_runtime()`，再进入装配函数看它创建了什么，最后回到入口看这些对象何时启动、何时关闭。
</callout>

---

## Gateway 第一次接收消息前，实际做了什么

Gateway 最能看清完整生命周期，因为它不只是运行 Agent，还要连接 Channel、定时任务和健康检查。正常启动路径可以压缩成下面这条链：

```text
gateway()
  → resolve_service_paths()
  → assemble_runtime()
  → runtime.start_memory_backend()
  → build_gateway()
  → cron.start() + health server
  → agent.run() + channels.start_all()
```

1. **解析服务路径。**确定这次 Gateway 使用哪个 workspace，以及运行状态放在哪里。
2. **统一装配 Runtime。**读取配置和插件注册信息，创建模型客户端、工具、会话管理器、记忆后端和 AgentLoop。
3. **启动异步后端。**如果配置了 MemoryBackend，在接收消息前先完成它的启动。
4. **构建 Gateway。**把 Runtime 交给 Gateway，并创建 Channel、Spine、Cron、QuestionBroker 等外围部件。
5. **启动辅助服务。**启动 Cron 和健康检查服务。
6. **运行 Agent。**AgentLoop 进入运行状态。
7. **最后开放输入。**各个 Channel 开始接收飞书等外部消息。

<callout emoji="✅">
走到最后一步，P00 里那条飞书消息才真正有机会进入 Pico。在这之前，系统做的都是“接线”和启动资源，而不是处理用户问题。
</callout>

---

## 一套 Runtime，哪些共同，哪些因入口而异

统一装配不等于三个入口完全一样。它统一的是核心对象的创建规则；界面、输入源和后台服务仍由各自的 Host 管理。

| 能力 | 统一装配负责 | Host 负责 |
|-|-|-|
| 模型与 AgentLoop | 按配置创建并注入依赖 | 决定何时调用和停止 |
| 会话 | 创建 SessionManager | 提供当前入口的会话标识 |
| 记忆 | 解析并创建 MemoryBackend | 在接收输入前启动，在退出时关闭 |
| 插件工具 | 从 Plugin Registry 解析并构建工具 | 不重复解析插件 |
| 输入与界面 | 不负责 | CLI 参数、TUI 界面或 Gateway Channel |
| 后台服务 | 不负责 | Gateway 的 Cron、Health、Spine 等 |

**读图时先看左右两侧：**左边是三个入口各自保留的差异；中间是唯一的统一装配入口；右边是所有 Host 都拿到的核心 Runtime。Plugin Registry 只参与创建阶段，真正交给 AgentLoop 的是已经构建好的插件工具。

![](images/P01/img1.jpg)

装配函数最终返回：

```python
@dataclass
class RuntimeAssembly:
    agent_loop: AgentLoop
    session_manager: SessionManager
    backend: MemoryBackend | None
```

这三个字段也划出了装配函数的边界：`agent_loop`负责一次次 Agent 推理与工具调用；`session_manager`负责会话状态；`backend`是可选的长期记忆后端。Channel、Cron 和健康检查不在这里，因为它们不是三个入口共同需要的 Runtime 核心。

---

## 创建完成，为什么还不能接收输入

`assemble_runtime()`返回，只能说明对象已经创建、依赖已经接好。某些资源还需要异步启动，例如记忆后端或 Channel 连接。Gateway 只有在这些关键步骤完成后，才开放外部输入。

| 教学阶段 | 系统正在做什么 | 此时能否接收外部输入 |
|-|-|-|
| 已配置 | 配置与路径已经确定 | 不能 |
| 已装配 | 核心对象已经创建并接线 | 不能 |
| 已启动 | MemoryBackend、Cron、Health 等资源启动 | 仍要等输入通道开放 |
| 已接收输入 | Agent 运行，Channel 开始收消息 | 可以 |

<callout emoji="💡">
上表是为了阅读源码而划分的教学阶段，不是源码中的正式状态机。还要注意：健康检查表示进程仍然存活，不等于所有依赖都已经准备好接收业务请求。
</callout>

**读下一张图时沿时间轴看：**上半部分是启动顺序，关键点是“先准备 Runtime，再开放输入”；下半部分是关闭顺序，关键点是“先停止新输入，再释放被使用的资源”。

![](images/P01/img2.jpg)

关闭不能简单地把启动顺序倒过来。Gateway 会先停 Health 和 Cron，再停止新输入，随后关闭 Spine 与 Channel transport；Agent 不再被外部调用后，才执行 `agent.stop()` 和 `runtime.close()`。最后由 Runtime 关闭 MCP、Sandbox，并停止 MemoryBackend。

---

## workspace 和 state 分别去哪里

入口统一以后，路径也必须统一解释。否则同一个 Gateway 可能在一个目录读取项目文件，却在另一个意外目录恢复会话或写运行状态。

```python
RuntimePaths(
    workspace=...,
    state_dir=...,
)
```

| 路径 | 它负责什么 |
|-|-|
| **workspace** | Agent 看到并操作的工作目录。文件工具、项目上下文和工作区约束都围绕它展开。 |
| **state_dir** | Pico 自己的运行状态目录，例如会话、缓存或服务状态。它描述“Pico 把自己的东西放哪”。 |

两者在某些配置下可以落到同一个物理目录，但语义不能混在一起：workspace 属于 Agent 的工作上下文，state_dir 属于 Runtime 的持久状态。把两者分开命名，后续才有可能安全地做多工作区路由或独立状态迁移。

---

## 失败以后，为什么处理方式不同

生命周期设计不只决定“成功时按什么顺序启动”，也决定失败发生时哪些错误必须阻止服务上线，哪些能力可以降级，以及清理过程能否继续。

| 失败位置 | Pico 的处理 | 原因 |
|-|-|-|
| 已配置的 MemoryBackend 启动失败 | 阻止 Gateway 进入接收输入阶段 | 用户明确要求了这项状态能力；带着不完整语义继续运行，可能让会话行为与配置承诺不一致。 |
| 某个可选插件工具构建失败 | 记录错误并跳过该工具 | 单个扩展不应必然拖垮整个 Agent；其他核心能力仍可能正常工作。 |
| 关闭某个资源时出错 | 继续清理其他独立资源 | 清理阶段的目标是尽可能释放所有权范围内的资源，不能因为前一个失败就把后面的资源全部遗留。 |

这三种策略背后是同一个判断：**它是不是用户明确配置的必要能力，它的失败会不会破坏 Runtime 的核心语义，它与其他资源能不能独立清理。**生命周期不是一串机械的 `start()` / `stop()`，而是一组关于依赖和所有权的决定。

---

## 回到开头

<callout emoji="✅">
三个入口之所以能表现一致，不是因为它们复制了相同代码，而是因为它们共享同一个装配边界：`assemble_runtime()`负责创建并连接核心对象，Host 负责启动自己的外围资源；接收输入之前完成准备，退出时按所有权停止并释放。
</callout>

**动手练习：**[E01｜沿 Gateway 启动路径找出 Runtime 的创建、启动与关闭位置](https://icnoljnkix43.feishu.cn/wiki/GIjHwgvMQiBSftkideacsQRKnGn#doxcnnBPYBfUCLfsMQeDAUJMc0g)

**下一篇：**[P02｜进入 AgentLoop：一条消息怎样变成一次完整执行](https://icnoljnkix43.feishu.cn/wiki/VN7cwTU2oiTkExk8uMxc46yFnUe)
