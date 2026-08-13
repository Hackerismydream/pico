# P08｜从飞书消息到最终送达：Gateway 怎样接住多入口

> 小林在飞书里发来任务。Pico 做完以后，回复还要经过一条独立的发送链路才能回到群里。本章沿着这条消息走一遍，再看 QQ、企业微信和定时任务怎样复用同一套运行时。

## 读前准备

这章会用到三个已经出现过的概念：

- **Turn**：Pico 对一条请求做出的完整反应；
- **Scheduler**：让同一会话按顺序执行、不同会话并行执行；
- **Runtime Event**：Agent Loop 向外发出的正文、媒体、工具进度和终态事件。

本章对应 `origin/main@9914182c7bafa3d3e2a7a5564e792fc9d6d524b7`。正文中的渠道列表、关闭顺序、定时任务认领和飞书投递语义都以这份 `main` 源码为准。

## 读完本章，你能回答什么

- 一条飞书消息怎样变成 `TurnRequest`？
- Feishu、QQ、WeCom 和 Cron 怎样共用 Runtime，又各自保留入口与出口？
- Agent 已经生成答案以后，回复为什么还可能发送失败？

## 先跟一条飞书消息走

小林在飞书群 `oc_team` 里发来一句话：

> 汇总今天失败的构建，把原因和负责人发回这个群。

平台 SDK 收到的是一条飞书事件，里面带着发送者、群聊、正文和附件。飞书适配器先提取字段，Intake 检查权限，再把消息交给共享 Runtime。Agent 生成的正文随后经飞书出口送回 `oc_team`。

先把实现名收起来，一条正常消息只做五件事：

```text
接收消息
→ 准入并整理成统一请求
→ 提交执行
→ 完成一条 Turn
→ 把回复发回原聊天
```

## 先认代码：一条消息的五站

| 阶段 | 主要文件与符号 | 这一站做什么 |
|-|-|-|
| 1. 接平台事件 | `pico/channels/adapters/feishu/channel.py` | 提取发送者、聊天、正文和附件 |
| 2. 准入并归一化 | `pico/channels/intake.py` | 检查权限，构造 `TurnRequest` |
| 3. 提交执行 | `pico/cli/gateway_commands.py` | 计算会话键，把普通消息提交给 Scheduler |
| 4. 运行 Turn | `pico/agent/spine_runner.py` | 调用共享 Agent Loop，产出统一事件 |
| 5. 发送结果 | `pico/spine/delivery.py` | 按渠道排队、重试并记录投递结果 |

这五站和下面的编号一致。ChannelManager 负责启停，Cron 是第二条入站路径，都放在主消息走完以后再看。

## 第 1 站：Channel 把平台差异留在边缘

当前 Gateway 注册的 IM 渠道有三个：

```text
feishu
qq
wecom
```

每个适配器都满足 `pico/channels/contract.py::Channel`。核心运行时只要求它提供：

```python
name
start()
stop()
send(chat_id, content, media)
```

飞书适配器知道怎样解析飞书事件、怎样判断 `chat_id` 和 `open_id`、怎样调用飞书 SDK。QQ 和 WeCom 也各自处理平台协议。它们都把入站消息交给 `Intake`，把出站发送收束到 `send()`，后面的 Session、Context、Memory 和 Agent Loop 因而只维护一份。

## 第 2 站：Intake 在调用模型前检查权限

在 Intake 仍然开放、发送者也已获准的正常路径里，`Intake.publish()` 收到发送者、聊天、正文、媒体和平台元数据后，会完成四个动作：

1. 用 `is_allowed()` 检查发送者；
2. 确认 Gateway 已经通过 `set_submit()` 绑定提交函数；
3. 构造 `Source`、`Media` 和 `TurnRequest`；
4. 等待 Gateway 的入站分发函数接住请求。

平台特有字段放进 `Source.extras`。当前飞书适配器会放入 `message_id`、原始 `chat_type` 和 `msg_type`。这些信息可以继续传递，又不会让 Scheduler 的公共请求类型不断增加平台字段。

这条飞书消息会形成：

```python
TurnRequest(
    origin=Origin.USER,
    source=Source(
        channel="feishu",
        chat_id="oc_team",
        sender_id="ou_xiaolin",
        chat_type=ChatType.GROUP,
    ),
    text="汇总今天失败的构建，把原因和负责人发回这个群。",
    conversation=None,
)
```

第一次看这个对象，只读三个字段：`source.channel` 决定回复渠道，`source.chat_id` 决定目标聊天，`conversation` 有值时覆盖默认会话键。

当前 Feishu adapter 不传 `session_key`，所以这里的 `conversation` 是 `None`。Gateway 和 Agent Loop 随后使用 `feishu:oc_team`，也就是 `source.channel + source.chat_id`，作为默认 conversation id。共享 Runtime 不会把不同渠道的聊天自动合成同一个会话。

权限检查发生在 Session、Context、Provider 和 Tool 之前。未授权消息到这里就结束，不会产生模型调用，也不会读取对话历史。

## 第 3 站：Gateway 把普通消息提交给 Scheduler

Gateway 启动后，会把每个 Channel 的 Intake 绑定到同一个 `_inbound_dispatch()`。对于小林这条普通消息，它先计算 conversation id，再把一条 `Origin.USER` 请求提交给 Scheduler。普通用户消息进入 USER 并发池，随后由 conversation id 选中对应 Lane。

## 第 4 站：共享 Agent Loop 执行这条 Turn

`_inbound_dispatch()` 把普通消息提交给 Scheduler 后，conversation id 选中对应 Lane，USER pool 决定它何时获得前台并发额度。

Lane 调用 `AgentTurnRunner.run()`。Runner 把请求、事件回调和运行中消息读取函数交给共享 Agent Loop。Session、Context、Memory、Provider 和 Tool 都从这里沿用同一套实现，不需要根据 Feishu、QQ 或 WeCom 复制。

这条任务完成时，Agent Loop 产出统一 `Text`。事件仍带着入站 `Source`，因此下一站知道它来自飞书群 `oc_team`。

## 第 5 站：DeliveryHub 把结果送回飞书

`build_gateway()` 为每个已构建 Channel 注册一个 `ChannelOutletAdapter`。Agent Loop 发出 `Text` 或 `MediaOut` 时，Gateway sink 把事件交给 DeliveryHub。

DeliveryHub 读取事件上的 `source.channel`：

```text
source.channel = feishu → Feishu Outlet
source.channel = qq      → QQ Outlet
source.channel = wecom   → WeCom Outlet
```

每个 Outlet 有一条容量为 100 的队列和一个串行 worker。同一渠道的事件按入队顺序发送，不同渠道各自消费自己的队列。飞书接口变慢时，飞书队列逐渐填满并反压飞书侧的生产者，QQ 和 WeCom worker 仍可继续发送。

这张图从左往右读。上半部分是三个 IM 入口怎样收束到共享 Runtime，下半部分补上 Cron 和 Subagent。最右侧重新分成三个出口，虚线标出了慢出口之间的隔离。

**图 P08-A｜多渠道消息怎样进入共享 Runtime，再回到各自出口**

![](images/P08/img1.jpg)

图里的 Intake 是进入 Agent 前的权限边界，Scheduler 管执行顺序和并发，DeliveryHub 管发送顺序和重试。三个职责分别位于消息链路的不同位置。

## 一次正常投递怎样完成

以飞书正文为例，`ChannelOutletAdapter.deliver()` 调用：

```python
await feishu_channel.send(chat_id, content)
```

这里的 `await` 表示当前异步动作要等发送结束；DeliveryHub 内部使用 `asyncio.Queue` 在产生回复的任务和渠道发送 worker 之间传递数据。

飞书 SDK 正常接受请求后，DeliveryHub 写入：

```text
channel.outcome = delivered
channel.attempts = 1
channel.retries = 0
```

调用方要区分两个等待点：

- `TurnHandle.result()` 等待 Agent 停止产生新事件；
- `DeliveryHub.wait_idle("feishu")` 等待飞书队列中已经入队的事件处理完。

Turn 完成时，回复可能还在队列里。需要确认终端已经处理完已入队内容时，再等待 `wait_idle()`。

## 主线走完以后，再看入口分支

普通消息已经从飞书走到 Runtime，再回到飞书。现在回头看几条不会改变主线结构、但会改变入口结果的分支。

### 渠道构建失败只影响对应适配器

`ChannelSpec.factory` 在真正启用渠道时才导入平台 SDK。列出渠道或读取配置时，不会提前加载所有可选依赖。某个 SDK 缺失或某个 factory 构建失败时，`ChannelManager` 只禁用对应适配器，其他已配置渠道仍可启动。

### Intake 会拒绝未获准或关闭后的消息

allowlist 默认拒绝。`["*"]` 允许所有发送者，空列表会拒绝所有人。`ChannelManager` 发现启用渠道的列表为空时，会直接禁用该渠道并记录配置错误，避免它保持在线却丢掉每条消息。

Gateway 关闭时会先调用 `Intake.seal()`，此后的新消息不会再进入提交链。已经越过准入点的 `publish()` 会被计入 inflight，关闭流程会等待它完成。

### 控制命令和运行中消息在提交前分流

`_inbound_dispatch()` 还会处理四种特殊情况：

| 入站内容或状态 | Gateway 的动作 |
|-|-|
| `/stop` | 取消该 conversation 的 Turn，并取消同 Session 的 Subagent |
| `/restart` | 先发送确认，再重启进程 |
| 正在等待 `ask_user` | 把这条消息交给 QuestionBroker |
| 同一 conversation 已有 Turn 在运行 | 以 `BusyPolicy.INJECT` 注入正在运行的 Turn |

控制命令不会进入 Agent Loop，也不会被模型当成普通聊天内容。Cron 和 Subagent 则进入 system 并发池，与 USER pool 分开计数。

## 飞书 SDK 拒绝消息时发生什么

网络断开可能短暂恢复，DeliveryHub 会按 1、2、4 秒退避重试，配置的 `send_max_retries=3` 表示初次尝试后最多再试三次。

飞书 SDK 也可能正常返回响应，但 `response.success()` 为 `False`，比如接收者 id 无效。`FeishuChannel` 会把这种业务拒绝转换成 `TerminalDeliveryError`。继续发送同一份请求无法修复接收者 id，DeliveryHub 因此在第一次尝试后结束重试，记录：

```text
channel.outcome = dropped
channel.error   = TerminalDeliveryError
```

DeliveryHub 支持一个独立的 failure sink。显式传入该回调时，`dropped` 会产生 `NoticeKind.DELIVERY_FAILED`；Notice 不会重新投给刚刚失败的渠道，避免形成发送失败循环。当前 `build_gateway()` 创建 DeliveryHub 时没有装配这个回调；确定性 V-TE0 场景会显式传入它，用来验证失败 Notice 与 Trace 的关联合同。

Agent 已经生成答案的 Turn 终态仍然保留为 `completed`，投递失败只写在 Delivery 这一侧。P10 会继续展开这两条终态轴。

## Cron 从另一侧提交系统 Turn

Cron Job 保存在 `jobs.json`。添加任务时，CronService 会先检查时间是否合法：

- `at` 要晚于当前时间；
- `every` 的周期要大于 0；
- `cron` 表达式和时区要能算出下一次触发时间。

到期后，`run_due()` 在文件锁内完成认领：

1. 重新读取 Store；
2. 找出启用、到期且渠道属于当前进程的 Job；
3. 写入 `claimed_by_pid` 和 `claimed_at_ms`；
4. 保存 Store，释放文件锁。

实际任务在锁外执行。这样一条耗时几分钟的 Job 不会占住整个 Cron Store。Gateway 的回调把 Job 变成 `Origin.CRON` 请求，提交到 Scheduler 的 system pool。

执行结束后，CronService 再次取得文件锁。只有仍持有相同 claim identity 的进程可以写回 `last_status`、下一次运行时间并清除 claim。

claim 超过 30 分钟后会被视为 stale，其他进程可以重新认领。这个恢复机制避免 Job 永久卡住，也留下外部动作可能重复的崩溃窗口。

下面这张图先读上方时间线，再看左下角的二维结果。右下角画的是进程崩溃窗口：外部动作已经发生、本地结果尚未写回时，claim 超时后可能再次执行。

**图 P08-B｜Cron 认领、Turn 执行和消息投递的两条结果轴**

![](images/P08/img2.jpg)

Cron 的 `last_status=ok` 说明回调正常结束。消息可能仍在 Outlet 队列中等待或重试，最终投递结果要继续看 `channel.deliver`。claim 协议减少并发重复认领，但外部副作用仍存在重复窗口。

## 一个日报 Job 的完整时间线

假设工作日 18:00 要把日报发到企业微信群：

```json
{
  "id": "job_daily_42",
  "schedule": {"kind": "cron", "expr": "0 18 * * 1-5", "tz": "Asia/Shanghai"},
  "payload": {
    "text": "汇总今天失败的构建",
    "channel": "wecom",
    "to": "room_dev"
  },
  "enabled": true
}
```

到期后的顺序是：

```text
写 claim
→ 提交 Origin.CRON Turn
→ system pool 等待或运行
→ Agent Loop 生成日报
→ Cron read-back 取得最终文本
→ Text 排入 WeCom Outlet
→ Cron 写回 last_status 和 next_run
→ WeCom worker 完成发送或记录 dropped
```

定时任务不会回填停机期间错过的每个周期。恢复后只处理当前 pending fire，再从恢复时间计算下一次运行，避免一次停机积累大量任务。

## Gateway 关闭时怎样收住入口和出口

长驻进程关闭时，最容易出问题的窗口是：Scheduler 已经停了，平台 callback 又送来一条消息。当前关闭顺序由 `_cleanup_gateway()` 固定：

1. 关闭健康端口；
2. 停止 Cron，阻止新定时触发；
3. 取消尚未回答的 QuestionBroker 请求；
4. `ChannelManager.quiesce_intake()` 封住所有 Intake；
5. 等待已经准入的 `publish()` 返回，五秒未结束时取消并确认 idle；
6. 收束 Scheduler，再关闭 DeliveryHub；
7. 逐个停止 Channel transport；
8. 停止 Agent 和 Runtime。

`quiesce_intake()` 与 `stop_all()` 分开。前者控制新的业务请求，后者停止平台连接。已经越过 Intake 准入点的消息会在 Scheduler 仍可用时排空。

Spine teardown 会尝试 Scheduler 和 Delivery 两个关闭屏障。即使 Scheduler 收尾抛错，Delivery 仍会被关闭。外部取消也要等已经开始的屏障结束后再向上抛出。

`DeliveryHub.aclose()` 会封住新 dispatch，取消 worker，并丢弃仍在内存队列中、尚未发送的事件。当前发送队列位于内存中，进程崩溃或关闭时被 drain 的内容不会自动补投。

## 走完以后，再整理术语

| 日常理解 | 代码名 | 负责什么 |
|-|-|-|
| 平台协议适配器 | Channel | 收平台事件，向平台发送 |
| 入站门 | Intake | 权限检查和请求归一化 |
| 长驻宿主 | Gateway | 把 Channel、Scheduler、Cron 和 Delivery 接起来 |
| 渠道发送口 | Outlet | 把统一事件转换为渠道的 `send()` |
| 出站队列管理器 | DeliveryHub | 路由、排队、重试和投递结果 |
| 定时任务认领 | claim | 用 PID 和时间记录当前执行者 |
| 执行结果 | Turn outcome | Agent 这一轮怎样结束 |
| 投递结果 | Delivery outcome | 终端内容是否送到渠道 |

## 失败时从哪一段链路查

| 现象 | 先看哪里 | 常见结果 |
|-|-|-|
| 渠道在线但所有人都进不来 | Channel 配置和 Manager 日志 | 空 allowlist 导致渠道被禁用 |
| 某个发送者进不来 | `Intake.is_allowed()` | allowlist 拒绝 |
| 日志显示 Intake 未绑定 | Gateway wiring | `set_submit()` 尚未执行 |
| Agent 已经结束，用户没收到 | `channel.deliver` | `dropped` 或 `no_outlet` |
| 飞书业务响应失败 | `FeishuChannel._send_message_sync` | `TerminalDeliveryError`，不做无意义重试 |
| 一个渠道慢，另一个也慢 | Delivery 队列与 Outlet 注册 | 检查是否绕过了 per-Outlet queue |
| Cron 长期不运行 | Job 的 channel、next run 和 claim | 不属于本进程或存在新鲜 claim |
| Cron 可能重复执行 | 外部副作用与 claim 写回时序 | 进程在两者之间崩溃 |
| Gateway 退出时仍有回调 | Intake seal 与 inflight 计数 | 检查 quiesce 是否先于 Spine teardown |

## 从哪些文件开始读

| 顺序 | 文件与符号 | 只看什么 |
|-|-|-|
| 1 | `pico/channels/intake.py::Intake.publish` | allowlist、Source 和 conversation |
| 2 | `pico/cli/gateway_commands.py::_inbound_dispatch` | 控制命令、问答回复和 INJECT |
| 3 | `pico/cli/_gateway_spine.py::build_gateway` | Scheduler、Hub 和 Outlet 怎样连接 |
| 4 | `pico/spine/delivery.py::DeliveryHub._enqueue` | 怎样按 source.channel 建队列 |
| 5 | `pico/spine/delivery.py::DeliveryHub._deliver_with_retry` | 临时错误和终止错误怎样收口 |
| 6 | `pico/channels/adapters/feishu/channel.py::FeishuChannel._send_message_sync` | SDK 的 `response.success()` 怎样变成发送结果 |
| 7 | `pico/proactive_engine/schedulers/cron/service.py::CronService.run_due` | claim、锁外执行和写回 |

源码锚点使用符号名。代码移动后，可以从符号搜索到当前实现，不需要依赖旧行号。

## 用测试验证理解

| 想验证什么 | 先读哪个测试 |
|-|-|
| Channel 能力与 adapter 注册 | `tests/test_channels_contract.py`、`tests/test_channels_registry.py` |
| allowlist、归一化和 Intake seal | `tests/test_channels_intake.py` |
| 渠道构建失败和有界停止 | `tests/test_channels_manager.py` |
| 飞书 SDK 业务拒绝怎样进入 dropped | `tests/test_channels_feishu.py` |
| 每出口顺序、跨出口隔离和重试 | `tests/test_spine_delivery.py` |
| Gateway 入站与关闭顺序 | `tests/test_cli_gateway_commands.py`、`tests/test_cli_gateway_spine.py` |
| Cron claim 所有权和结果写回 | `tests/test_cron_service_claim.py`、`tests/test_cron_service_outcomes.py` |
| Cron 文本怎样进入指定出口 | `tests/test_cron_delivery.py` |

这些测试验证本地执行合同。它们不测真实平台网络的长期稳定性，也不提供线上渠道 SLO。

## 25 分钟代码练习

目标：追完一条飞书正文从入站到 `channel.deliver` 的路径。

1. 第 1 站，在 `FeishuChannel` 找到调用 `intake.publish()` 的位置；
2. 第 2 站，在 `Intake.publish()` 记下 `Source` 的三个关键字段；
3. 第 3 站，找到 Gateway 注入的 `_inbound_dispatch()` 和普通消息分支；
4. 第 4 站，沿 `Scheduler.submit()` 找到 `AgentTurnRunner.run()`；
5. 第 5 站，在 `build_gateway()` 找到 Feishu Outlet 的注册；
6. 沿 `Text` 找到 `_enqueue()` 和 `_deliver_with_retry()`；
7. 在 `FeishuChannel._send_message_sync()` 找到 `response.success()` 的判断；
8. 对照测试，分别写出成功、网络重试耗尽和业务拒绝的 outcome。

建议边读边填：

```text
阶段 | 输入类型 | 决定路由的字段 | 可能失败 | 下一站
```

完成后回答：

- 为什么 `TurnHandle.result()` 返回时，用户仍可能没收到消息？
- 飞书业务拒绝为什么只尝试一次？
- Gateway 为什么先 seal Intake，再关闭 Scheduler？

## 本章复盘

- [ ] 能画出平台事件到 `TurnRequest` 的入站链路；

- [ ] 能说出 Channel、Intake、Gateway 和 DeliveryHub 的分工；

- [ ] 知道当前 Gateway 注册 Feishu、QQ 和 WeCom；

- [ ] 知道 allowlist 在模型调用之前执行；

- [ ] 能解释 per-Outlet 队列怎样隔离慢渠道；

- [ ] 能区分 `result()` 与 `wait_idle()`；

- [ ] 能解释飞书业务拒绝、`dropped` 和 `DELIVERY_FAILED` Notice 的关系；

- [ ] 能区分 Turn outcome 与 Delivery outcome；

- [ ] 能复述 Cron 的 claim、锁外执行和结果写回；

- [ ] 知道 claim 协议仍有外部副作用重复窗口；

- [ ] 能复述 Gateway 的关闭顺序；

- [ ] 知道内存发送队列不会在崩溃后自动补投。

## 接下来怎么读

- [P09｜TokenWise 与 Provider 成本](https://icnoljnkix43.feishu.cn/wiki/Gs8XweE8hi6bXBkhWL6cKOnEn2c)：同一次 Agent 任务为什么会重复计算输入成本；
- [P10｜Tracing 与终态](https://icnoljnkix43.feishu.cn/wiki/OS4WwBltmi3v5gkfmQ8cPVmOnec)：怎样把执行成功和投递成功分别记录；
- [面试总话术](https://icnoljnkix43.feishu.cn/wiki/H9rewOY10ixocdkYCuwcIHqjneY)：准备项目表达时，再进入逐字话术线。