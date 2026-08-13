# P00｜从一条飞书消息认识 Pico

<callout emoji="📌">
本章先不展开 Memory、Tracing、Subagent，也不要求你把仓库从头读一遍，我们只跟着一条飞书消息往前走，看看 Pico 为什么不是一个模型调用脚本，以及它到底接住了任务的哪一段生命周期。
</callout>

## Pico 为什么存在

今天并不缺少开源 Agent。

OpenClaw 想成为运行在用户设备和聊天软件里的个人 AI 助手，Hermes 强调长期记忆、Skill 学习和无人值守自动化，nanobot 则尝试用一个足够小、足够容易修改的内核，提供个人 Agent 所需要的常见能力。

Pico 选择回答另一个问题：

> 当入口、模型、工具和任务都在变化时，怎样保证它们仍然服从同一套执行契约，并且能够解释这次任务为什么完成、为什么失败、结果有没有送达、证据是否足以支撑结论？

这也是 Pico 所说的 Agent Harness。

Pico 不训练模型，也不试图用更多渠道、更多内置工具或者一个更热闹的 Skill 市场取胜。它把 CLI、TUI、Gateway、Cron 和聊天 Channel 接入同一套 Runtime，让它们提交相同的 Turn，由 Spine 管理会话内顺序和取消，由 Agent Loop 推进模型与工具，由 Session、Context 和 Memory 分别承担不同生命周期的状态，最后由 Delivery 把结果交回正确入口。

这条链路刻意区分了几件经常被混在一起的事：

- 一次模型调用不是一条 Turn。
- 模型生成正文不代表结果已经投递。
- Tool 执行失败不一定等于整条 Turn 失败。
- 代码已经实现，不代表测量一定有效。
- 候选通过评测，也不代表它可以自动替换正在运行的系统。

因此，Pico 的差异不在于让 Agent 看起来更聪明，而在于让 Agent 的执行、失败、证据和演化都有明确所有者。

它也有清楚的边界。Pico 不是面向消费者的个人 AI 全家桶，不是只服务编码任务的 Coding Agent，也不宣称能够自主修改和部署自己。当前的 Evolver 只会产生可评审的候选、评测结果、激活决定和回滚证据，是否启用仍由人决定。

理解 Pico 最有效的方法，也不是先读完每个目录，而是先跟着一条请求走完整条链路。接下来我们从一条飞书消息开始，看它怎样变成 Turn，怎样进入 Lane，怎样让模型与工具反复协作，又怎样留下 Session、Trace 和最终投递结果。

<callout emoji="💡">
这里说的 Turn，是 Pico 对一条请求做出的完整 Agent 反应，它可以包含很多次模型调用和工具执行，不要把一次 LLM 请求叫作一条 Turn。
</callout>

---

## 先看一件很具体的事

小林在飞书私聊里发来一句话：

> 读取仓库里的 pytest 配置，并告诉我最容易漏掉的失败路径。

模型不可能只看这句话就知道仓库里有什么，它至少要读配置，可能还要继续查测试目录，然后把看到的内容整理成回答。对小林来说，这只是发出一条消息再等结果；对 Pico 来说，它要接住来源、找到对话、安排执行、让模型使用工具、保存这轮消息，最后把正文送回同一个私聊。

把中间细节先压扁，大致就是下面这条链：

```text
飞书收件 → 整理成 TurnRequest → 进入 conversation 对应的 Lane
        → Agent Loop 调用模型与工具 → 保存 Session → 交给 DeliveryHub 发送
```

这条线现在不需要背，先看懂每一段为什么存在，后面的章节会再把它们放大。

**图 P00-A｜一条飞书消息在 Pico 里的代码落点**

![](images/P00/img1.jpg)

---

## 平台差异应该停在入口

飞书送进来的不是一段干净文字，而是一份平台事件，里面带着消息类型、发送者、聊天地址和回复位置。`FeishuChannel._on_message()` 会把这些东西拆出来，再交给 `Intake.publish()`，这里最重要的不是飞书字段有多少，而是平台信息到这里就该收住，后面的 Runtime 不应该到处判断“这是飞书还是别的平台”。

Intake 会把消息整理成 Pico 统一认识的 `TurnRequest`，下面只保留这章需要看的字段：

```python
TurnRequest(
    origin=Origin.USER,
    source=Source(
        channel="feishu",
        chat_id="ou_xxx",
        sender_id="ou_xxx",
        chat_type=ChatType.DM,
    ),
    text="读取仓库里的 pytest 配置，并告诉我最容易漏掉的失败路径。",
    conversation=None,
)
```

`origin` 说明请求从哪里来，`source` 留下回复地址，`text` 是任务本身。普通飞书私聊没有显式提供 `conversation` 时，Scheduler 会用渠道名和聊天地址得到默认 key，例如 `feishu:ou_xxx`，这样下一句话进来时还能回到同一段 Session。

很多入口问题到这里就已经解决了：飞书负责把消息递进来，Intake 负责把它变成统一形状，往后的调度和执行只认 `TurnRequest`。

---

## 同一段对话不能同时跑两条 Turn

请求整理好以后会进入 `Scheduler.submit()`，Scheduler 根据 conversation 找到对应的 Lane。可以把 Lane 理解成一段对话自己的单行通道，同一个 conversation 一次只运行一条 Turn，不同 conversation 则可以并行。

这样做不是为了把队列搞复杂，而是同一段对话共享 Session，通常也在操作同一个 workspace，两条 Turn 如果同时读写，后发生的消息可能看不到前一条结果，工具也可能一起改同一个文件。Pico 先用 Lane 钉住会话内顺序，再把跨会话的并行交给调度器，具体的 APPEND、INJECT、INTERRUPT 和并发池留到 P02 再讲。

<callout emoji="💡">
Lane 管同一段对话的顺序，并发池管整个 Runtime 的容量，这是两件不同的事。
</callout>

---

## 真正干活的是一个循环

轮到这条请求执行时，Scheduler 不直接调用模型，它通过 Turn Runner 把请求交给 `AgentLoop.run_turn()`。Agent Loop 先找到这段对话的 Session，再让 Context Engine 把系统规则、历史消息和当前任务组装成模型真正看到的输入，然后交给 Provider。

模型第一次可能只返回一个工具请求：读取 `pyproject.toml`。Tool Registry 校验参数并执行工具，文件内容作为 `ToolResult` 回到 messages，Agent Loop 再调用一次模型；如果模型还想继续查测试配置，这个过程会接着走，直到它不再请求工具，给出最终正文。

```text
准备 Context
→ 调用 Provider
→ 模型请求 Tool
→ 执行 Tool，把结果写回 messages
→ 再次调用 Provider
→ 得到最终正文
```

Turn 内每一次模型推进，以及紧跟着的工具处理，叫一次 Iteration。一条 Turn 可以有很多次 Iteration，某次工具失败也不一定让整条 Turn 失败，错误会回到模型，它可以改参数、换工具，或者把限制解释给用户。

---

## 结果生成以后，事情还没有完全结束

模型形成最终正文后，Agent Loop 会把这轮需要保留的消息写进 Session，下一条消息到来时，Context Engine 才能接着这段历史工作。随后正文沿 emit 出口进入 DeliveryHub，DeliveryHub 根据来源找到飞书出口，放进对应的发送队列，再由后台 worker 调用平台 API。

这里很容易把几个时间点揉在一起，其实它们不是一回事：

| 时间点 | 说明 |
|-|-|
| Session 已保存 | 这轮对话记录已经写入状态目录 |
| Turn 已结束 | Lane 已经拿到本轮执行终态，不会再产生新的 Runner 事件 |
| Delivery 已完成 | 飞书出口已经返回 delivered、dropped 或 no_outlet |

所以“Agent 已经做完，但飞书没有收到”完全可能发生，排障时应该从 Delivery 往后查，而不是让模型重新做一遍任务。Pico 能观察到的是平台 API 是否接受了发送，用户有没有真正读到消息，属于飞书自己的范围。

**图 P00-B｜Turn 结束与 Delivery 完成不是同一个时刻**

![](images/P00/img2.jpg)

---

## 代码里的主干其实不长

第一次打开仓库，我不建议按目录从上往下读，沿着这条请求找入口会舒服很多：

| 发生了什么 | 主要入口 |
|-|-|
| 飞书事件变成可处理的消息 | `pico/channels/adapters/feishu/channel.py` |
| 平台消息变成 TurnRequest | `pico/channels/intake.py`、`pico/spine/turn.py` |
| conversation 找到自己的 Lane | `pico/spine/scheduler.py` |
| 模型和工具反复推进 | `pico/agent/loop/main.py` |
| 对话历史写进 Session | `pico/session/manager.py` |
| 最终正文进入渠道出口 | `pico/spine/delivery.py` |

如果某个类暂时看不懂，先问它接住了什么、交给了谁、没有它会乱在哪里，这比逐行解释函数更容易抓住设计。想自己走一遍源码，可以去做 [E00｜画出一条 Turn 的所有权链](https://icnoljnkix43.feishu.cn/wiki/GIjHwgvMQiBSftkideacsQRKnGn#doxcnJcoyNHiiWsbEftqZrF8G9b)，这是可选练习，不影响继续读正文。

---

## 回到开头，Pico 到底是什么

<callout emoji="✅">
Pico 是一套把 Agent 任务装进明确生命周期里的 Harness，外部入口把消息交进来，Spine 负责顺序和终态，Agent Loop 负责模型与工具的多轮推进，Session 保存对话，DeliveryHub 再把结果交回原来的入口。
</callout>

它没有替模型思考，也没有替飞书保证用户已读，它做的是把两者之间那段最容易失控的运行过程管起来。

这一章故意只保留主干，Memory 怎样进入 Context、Provider 为什么会重试、工具怎样隔离执行、Trace 怎样留下证据，后面都会单独讲。下一篇先往消息到来之前退一步，看 CLI、TUI 和 Gateway 为什么不能各自随便装一套 Agent，以及 Runtime Assembly 到底替它们收住了什么。

继续阅读：[P01｜Runtime Assembly：消息到来前，谁把系统接好](https://icnoljnkix43.feishu.cn/wiki/VQyiwRnCUiwqSGkwkx6clJNNn8b)
