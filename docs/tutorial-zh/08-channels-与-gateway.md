# 08 Channels 与 Gateway：把消息平台接进来，还要说得清接到了哪一步

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。#22 已完成，#21 仍无 passed V-LF。本章有三处机制晚于代码基线（飞书适配器的四条日志回执来自 PR #48；`ChannelSpec.maturity` 字段与 V-S0 门来自 PR #50），出现的地方逐处标注。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。
> 其中临时配置关闭 EverOS 的写法属于历史快照；当前最小配置使用 `memory.backend = null`。

读完这一篇，你应该能回答：

- 加一个新 IM 平台要动几个文件，为什么注册表里一行 `if channel == ...` 都没有
- 一个平台的 SDK 没装上，为什么只有那个 channel 死，以及基线上这条隔离在哪里破了个口
- gateway 收到一条入站消息，四个分支怎么排优先级，忙的时候为什么是 INJECT 而不是排队
- 飞书 bot 不能给自己发消息，那 live 门怎么自动化，刺激没来算什么结果
- Beta 和 live-gated 之间差的到底是什么，为什么改一个字段要连着改四个展示面

## 一、问题：把 agent 接进飞书群

你已经有一个能跑的 agent：CLI 里问它，它读文件、跑命令、给答案。现在要把它放进飞书群，@ 一下就干活。听起来只是换个输入源，实际要回答一串问题：谁允许说话；群里怎么算在叫它；语音消息怎么变成文字；它回话回到哪个会话；上一条还没答完又来一条怎么办；飞书那条长连接断了，整个进程要不要跟着死。

朴素做法的四种翻法，按被抓住的难度从易到难：

1. **在 gateway 里按名字分发。** `if channel == "feishu": ... elif channel == "qq": ...`。加第四个平台要同时改 gateway 主体、`channels list`、`doctor`、引导流程，改漏一处就出现「列表里有、实际起不来」这种最难查的不一致。
2. **SDK 写在模块顶层。** `import lark_oapi` 放在文件第一行，没装 `channel-feishu` 这个 extra 的人跑 `pico --help` 就吃到 ImportError。反过来，为了用一个平台把三家 SDK 全装上，也是同一个病的另一面。
3. **忙的时候老实排队。** 用户连发三条「等下」「算了」「你先看第二个文件」，调度器排出三个独立 turn，第一个 turn 还在读第一个文件，后两条要等它把错的活干完。
4. **mock 测完就宣布接入。** 适配器单测全绿，`send` 被断言调用了一次、参数也对，简历上写「已接入飞书」。真实的 token 过期、群里 mention 的结构、语音的 opus 编码、断线重连后事件重投，一条都没碰过。

前三条是设计题，最后一条是诚实题。它决定了本章最后三节的写法，也决定了这一章里唯一那个必须反复标注的边界：飞书至今没有一次通过的 live 门。

## 二、契约：一个协议、一份描述符、一次扫描

`pico/channels/contract.py` 只有 84 行，它规定的东西比行数多。核心是三件：`Channel` 协议（`start` / `stop` / `send` 加 `name` 和 `capabilities`）、可选能力用独立的 `Supports*` 协议 opt-in、每个适配器包导出一个 `ChannelSpec`。模块 docstring 里那句 composition over inheritance 后面跟了一句更硬的话：there is no base class to subclass，适配器靠结构化满足协议，框架服务（intake、转写）是注入进去的。

读到这里如果你去翻适配器代码，会立刻发现一个看似矛盾的事实：仓库里有个 `ChannelBase`，三个适配器全都继承了它。`pico/channels/base.py` 的 docstring 专门把这两件事切开：ChannelBase 是 thin construction plumbing only，它做的全部事情是省掉每个适配器 `__init__` 里重复的三行（存 config、置 `_running = False`、注入 `Intake`）；系统其余部分依赖的契约是 `Channel` 协议，原文写的是 inheriting here is for code reuse; conformance is by protocol。区别能在类型系统里摸到：`Channel` 是 `@runtime_checkable` 的 Protocol，一个不继承 ChannelBase 的类只要结构上有那五个成员，`isinstance(obj, Channel)` 照样为真。继承是省样板的手段，协议才是被依赖的接口；「你不是说没有基类吗」是这个模块最容易被追进来的口子，答案就是上面这两句 docstring。

`ChannelSpec` 是本章第一个承重名词，它的实物就是飞书适配器包里那个 19 行的 `spec.py`，全文如下：

```python
"""Declarative descriptor for the Feishu channel. Importing this module does not
import lark_oapi — the SDK import is deferred into the factory."""

from __future__ import annotations

from pico.channels.contract import Capabilities, ChannelSpec


def _make(config):
    from pico.channels.adapters.feishu.channel import FeishuChannel

    return FeishuChannel(config)


SPEC = ChannelSpec(
    display_name="Feishu",
    factory=_make,
    capabilities=Capabilities(),
)
```

`factory` 里那个函数级 import 是整个设计的支点：加载这份 spec 不会碰 `lark_oapi`，所以列举、引导、登录路由这些「只是想知道有哪些 channel」的场景全是廉价的。QQ 和 WeCom 的 `spec.py` 逐字同构，也是 19 行。

注册表因此可以做到零硬编码，`registry.py` 一共 48 行，主函数是这段：

```python
def discover_specs() -> dict[str, ChannelSpec]:
    """Return ``{name: ChannelSpec}`` for migrated adapters, keyed by package
    name.
    """
    import pico.channels.adapters as pkg

    specs: dict[str, ChannelSpec] = {}
    for _, name, ispkg in pkgutil.iter_modules(pkg.__path__):
        if not ispkg:
            continue
        try:
            mod = importlib.import_module(f"{_ADAPTERS_PKG}.{name}.spec")
        except ModuleNotFoundError:
            continue  # not yet migrated
        if (spec := getattr(mod, "SPEC", None)) is not None:
            specs[name] = spec
    return specs
```

同文件里还有一个 `discover_channel_names`，注释写明它的扫描只有一层深，所以适配器包内部的 `parsing.py`、`cards.py` 这类辅助模块不会被误认成 channel。`ChannelSpec` 里刻意不放的东西也值得记：channel 的名字就是包名（注册表的键），依赖提示和配置项由 CLI 从 capabilities 加配置 schema 现推。能从别处查到的，不复制进描述符。

契约文件的最后 25 行（60 到 84 行）容易被跳过，却值得单独讲：`capability_violations`。能力声明（`Capabilities` 上的布尔位）和能力实现（`Supports*` 协议）是两张皮，两张皮就会漂移：声明了 `interactive_login` 却没实现 `SupportsLogin`，CLI 会给用户一个点不动的 login 入口；实现了却没声明，功能永远不会被路由到。contract.py 的处理是一张对照表加一个双向检查：

```python
_CAP_PROTOCOLS: tuple[tuple[str, type], ...] = (
    ("interactive_login", SupportsLogin),
    ("streaming", SupportsStreaming),
)


def capability_violations(channel: object, caps: Capabilities | None = None) -> list[str]:
    caps = caps if caps is not None else getattr(channel, "capabilities", Capabilities())
    out: list[str] = []
    for flag, proto in _CAP_PROTOCOLS:
        declared = getattr(caps, flag)
        implemented = isinstance(channel, proto)
        if declared and not implemented:
            out.append(f"declares {flag} but does not implement {proto.__name__}")
        if implemented and not declared:
            out.append(f"implements {proto.__name__} but does not declare {flag}")
    return out
```

对照表上方的注释写了维护规则：Adding a capability = add one row; the check below covers both directions for it。这个函数被每个适配器的 capability-proof 测试调用，所以「声明表」旁边始终站着一个证明器。第九节 maturity 误标那次翻车，出事的正是一张当时还没有证明器的声明表：字段可以自由声明，没有任何检查要求它有背书。

回到「加一个平台要动几个文件」这个面试题：新建 `pico/channels/adapters/<name>/`，写一个 `spec.py` 和一个 `channel.py`，在配置 schema 里加一节，在 `pyproject.toml` 里加一个 extra。`channels list`、`channels status`、`doctor`、引导流程、`ChannelManager` 一行都不用改，因为它们全部走 `discover_specs()`。

## 三、可选依赖：一个 SDK 缺席，不该拖垮别人

extras 的命名是一一对应的：`channel-feishu` 装 `lark-oapi`，`channel-qq` 装 `qq-botpy`，`channel-wecom` 装 `wecom-aibot-sdk-python`，再加一个聚合 extra `channels` 把三个都拉进来。基础安装一个 IM SDK 都不带。

`ChannelManager._init_channels` 是这条隔离的执行点：

```python
for modname, spec in discover_specs().items():
    section = getattr(self.config.channels, modname, None)
    if not section or not getattr(section, "enabled", False):
        continue
    try:
        channel = spec.factory(section)
        channel.transcription_api_key = groq_key
        self.channels[modname] = channel
        logger.info("{} channel enabled", spec.display_name)
    except ImportError as e:
        logger.warning(
            "{} channel disabled: missing dependency ({}). {}",
            modname,
            e,
            _missing_dep_hint(modname),
        )
```

`_missing_dep_hint` 这个辅助函数把「你该怎么装」这件事做对了一层别人常忽略的细节：它读 PEP 610 的 `direct_url.json` 判断当前是可编辑安装还是 wheel 安装，前者提示 `uv sync --extra channel-<name>`，后者没有源码树，只能提示重跑安装脚本。它的 docstring 还写明这段代码运行时 channel 已经在失败路径上，所以文件缺失或损坏必须降级成安装器提示，绝不能自己再抛一次。

基线上这条隔离有两个破口，得如实说。第一个藏在上面那段代码里：try 只接住 `ImportError`。工厂如果抛出任何别的异常，比如配置值类型不对触发的 ValueError，或者 SDK 版本不兼容触发的 AttributeError，异常会从 `_init_channels` 一路冒出去，gateway 整个起不来。PR #50（晚于代码基线）补了一个 `except Exception` 分支，日志措辞是 adapter failed to construct，并在 V-S0 里用具名的 `test_factory_crash_disables_only_that_channel` 和 `test_gateway_still_constructs_when_every_channel_fails` 钉住。

第二个破口更显眼。同一个类里的 `_validate_allow_from` 在发现某个 channel 的 `allow_from` 是空列表时，直接 `raise SystemExit`：

```python
def _validate_allow_from(self) -> None:
    for name, ch in self.channels.items():
        if getattr(ch.config, "allow_from", None) == []:
            raise SystemExit(
                f'Error: "{name}" has empty allowFrom (denies all). '
                f'Set ["*"] to allow everyone, or add specific user IDs.'
            )
```

一个 channel 配错了 allowlist，整个 gateway 起不来，另外两个 channel 陪葬。PR #50（晚于代码基线）把它改成只禁用那个 channel 并打 error 日志，main 上 `_validate_allow_from` 的 docstring 把两难写全了：空 allowlist 的 channel 留着不动，它就是一个静默丢掉每条入站的黑洞，所以要大声禁用（dropped loudly instead of being left running as a black hole）；但也不能中止进程，原话是 instead of aborting the process, which would let one channel's config error take down every other one。讲这一节时把两个版本都说出来，比只讲修好的版本更能说明「隔离」这个词有多容易只做一半。

顺带一个和依赖无关但同源的细节：空 allowlist 等于拒绝所有人，`*` 等于放行所有人，这个语义写在 `pico/auth/allowlist.py` 的模块 docstring 里，理由是 so a misconfigured channel doesn't accidentally accept the whole internet。它还做了一件小事，同一个 channel 因为空 allowlist 拒绝时只警告一次，用模块级的 `_warned_empty` 集合记着，免得每条入站刷一行日志。

## 四、入站：四个分支的优先级

`Intake` 是注入进每个适配器的入站闸门，103 行，职责窄到只有两件：查权限，然后把消息构造成 `TurnRequest` 交给 spine。它自己的 docstring 说明了为什么不做更多：分发是 control-aware 的（要拦 `/stop` 和 `/restart`），而控制与取消的逻辑住在调度器和 agent 所在的地方，也就是 gateway。

gateway 那一端就是 `_inbound_dispatch`，本章最值得逐行读的一段：

```python
async def _inbound_dispatch(req) -> None:
    cmd = req.text.strip().lower()
    cid = req.conversation or f"{req.source.channel}:{req.source.chat_id}"
    if cmd == "/stop":
        stopped = gw_scheduler.cancel_conversation(cid)
        stopped += await agent.subagents.cancel_by_session(cid)
        content = f"Stopped {stopped} task(s)." if stopped else "No active task to stop."
        await gw_hub.dispatch(Text(content=content, source=req.source))
    elif cmd == "/restart":
        ...
    elif question_broker.pending_req(cid) is not None:
        # This conversation is blocked on an ask_user question —
        # route the answer to the broker (resolving the awaiting
        # tool) instead of starting or injecting a turn.
        question_broker.reply(cid, req.text)
    elif gw_scheduler.has_inflight(cid):
        # A turn is already running this conversation — submit as
        # BusyPolicy.INJECT so the loop merges this message at its
        # next iteration instead of queuing a fresh turn.
        gw_scheduler.submit(replace(req, busy=BusyPolicy.INJECT))
    else:
        gw_scheduler.submit(req)  # fire-and-forget (no readback)
```

四个分支的排序不是随手写的，每一条都在挡一个具体的坏结果：

`/stop` 和 `/restart` 排最前，因为它们不能被当成 turn 提交。上面代码块的注释写了理由：else the agent would reply to the text，模型会认真地回答「好的，我这就停下」，然后什么也不停。`/stop` 同时取消调度器里那条 lane 和这个会话名下的所有 subagent，回执直接报数字。

`ask_user` 待答优先于「忙」。一个会话正卡在 `ask_user` 上等人回答时，用户的下一条消息是答案，不是新任务。走 broker 的 `reply` 会解开那个挂起的工具调用；如果这一分支放在忙检查之后，答案会被 INJECT 进正在等答案的那一轮，形成一个自己等自己的死结。

忙则 INJECT，不排队。`has_inflight` 为真说明这条会话有 turn 正在跑，此时提交用 `BusyPolicy.INJECT`。调度器对 INJECT 的处理写在每条 Lane 的 `submit` 里（`Scheduler.submit` 按会话把请求路由到对应 lane）：请求进这条 lane 的 `_inject_mailbox`，等运行中的那一轮在工具循环的间隙把它 drain 进来并入上下文；如果那一轮结束时还没 drain，worker 的 finally 块会把它退回成一个普通 APPEND turn，注释里写着 no message lost，USER 来源的退回还会打一条 `inject fell back to append (not merged)` 的日志，免得「我插的话怎么没进去」变成查不动的悬案。用户补的那句「算了，看第二个文件」因此能在同一轮里被模型看到，而不是排队等一轮错的活干完。这个策略还有一条边界：`_effective_busy` 把非 USER 来源请求的 INJECT 和 INTERRUPT 一律降级成 APPEND 并把 requested 与 applied 两个值都写进日志，docstring 给的理由是系统来源不允许打断或插进用户的轮次。

都不是，就当普通 turn 提交，fire-and-forget。回复不靠调用方读回，走 emit 到 hub 再到 outlet。

### 一条消息的完整时间线

把上面这些串成一条真实路径，以飞书私聊为例，逐段都能在代码里点到位置：

1. lark SDK 的 WebSocket 线程收到事件，调 `FeishuChannel._on_message_sync`。这里第一件事是查 `self._running`，注释解释了为什么：`lark.ws.Client` 没有 `stop()`，socket 可能活得比 `stop()` 久并继续投递，所以停掉或重启过的实例必须在这里把僵尸投递丢掉。
2. 通过 `run_coroutine_threadsafe` 跳回主事件循环，进 `_on_message`。按 `message_id` 查 1000 条容量的 `OrderedDict` 去重（`_DEDUP_CAP = 1000`，塞满后 `popitem(last=False)` 淘汰最老的），命中就返回，main 上这里还会先打一条 `Feishu duplicate event suppressed` 的回执（PR #48 加的，基线上是静默丢弃）；`sender_type == "bot"` 直接丢弃。
3. 群消息先过 `_addressed_to_bot`：`group_policy` 是 `open` 就都算，否则要求 `@_all` 或 mentions 里有一个 open_id 型的 id。
4. 查 allowlist。这一步刻意排在表情回应和媒体下载之前，源码里那行注释就是 `# reject before react / media download`，被拒的发送者不会让 bot 冒泡也不会触发一次下载；main 上拒绝时打 `Feishu inbound rejected by allowlist: sender=...`（同样来自 PR #48）。
5. 通过之后先打一个表情回应（`config.react_emoji`）作为「收到了」的 UX，再走 `_extract`：文本直接取；图片、音频、文件走 `_download_media` 落盘；音频额外走 `_transcribe`，先试飞书自家的 `file_recognize`，失败再落到 Whisper。
6. main 上这里打一条 `Feishu inbound accepted: message_id=... chat_type=... msg_type=...` 的回执（PR #48 加的），然后 `intake.publish`。回复地址在这里定：群聊回 `chat_id`，私聊回 `sender_id`。
7. `Intake.publish` 再查一次权限（适配器的 `is_allowed` 被作为 `allow_check` 注入，所以两处用的是同一套判断），构造 `TurnRequest` 交给 `_inbound_dispatch`，进上面那四个分支。
8. turn 跑完，`Text` 事件经 `DeliveryHub` 路由到 `ChannelOutletAdapter`，落到 `FeishuChannel.send`。main 上发送成功打 `Feishu message sent: msg_type=... message_id=...`；基线上 `_send_message_sync` 成功时静默返回 True。

第 2、4、6、8 步提到的四条日志回执（重复抑制、allowlist 拒绝、入站接受、发送成功）全部晚于代码基线：`76d3761` 的适配器在这四个点位是静默的，它们随 PR #48 的 V-LF harness 一起加进来，因为它们是 V-LF 唯一的观测点。措辞被确定性测试逐字钉住不是修辞，main 上 `tests/test_channels_feishu.py` 的断言精确到整行：`assert receipts == ["Feishu inbound accepted: message_id=m1 chat_type=p2p msg_type=text"]`；QQ 和 WeCom 在 PR #50 也拿到了同一套回执和同样逐字的断言。第七节会讲为什么必须是日志回执而不是返回值。

## 五、出站与 gateway 进程

出站侧只有 40 行的 `ChannelOutletAdapter`，把一个 channel 包成 spine 的 Outlet：`Text` 调 `send`，`MediaOut` 调 `send(chat_id, "", media=[...])`，`StreamDelta` / `Reasoning` / `ToolEvent` / `Notice` 全部吃掉，因为 channel 是非流式的，只显示最终回复。类 docstring 里那句边界写得很清楚：A real send failure raises, which the hub retries; eating is not failure。

`DeliveryHub` 给每个 outlet 一条有界队列加一个串行 worker。队列满了只堵这一个 channel 的发送方，不会跨 channel 头阻塞；同 channel 的顺序由那一个 worker 保证。默认队列上限 100（`_OUTLET_QUEUE_MAXSIZE = 100`），重试 3 次，退避从 1 秒起每次翻倍（源码注释：doubles each retry (1, 2, 4)）；退避耗尽后是一条 error 日志加放弃，不向上抛，一条发不出去的消息不该把这个 channel 的 worker 拖死。发到一个没注册 outlet 的 channel 时是 warning 加丢弃，不是异常。入队时发现这个 channel 的 worker 已经 done 会重新拉起一个，注释给的理由是 worker 常驻阻塞在 `get()` 上，死掉的 worker 会让队列失去唯一的消费者，这个 channel 之后的每个发送方都会静默卡死。关停时 `aclose()` 直接取消所有 worker，`drain()` 同步清空还没投出去的事件并返回条数；「在收尾窗口里尽力把在途的送完」在两处 docstring 里都被明确标成 not yet implemented，这也是一条要如实说的边界。

进程这一层有三件事值得讲。

单实例锁用的是 portalocker 的跨平台建议锁，POSIX 走 `fcntl`，Windows 走 `LockFileEx`，句柄握着整个进程生命周期，所以进程死掉（包括 SIGKILL）时 OS 自动释放，永远不需要清理陈旧锁文件。有个细节能看出是踩过坑的：锁加在 `gateway.lock.lck` 这个空锚文件上，而不是记录 pid 的 payload 文件上，注释给的理由是 Windows 上锁是强制的，锁 payload 会挡住 `doctor` 读属主 pid。锁的路径挂在实例数据目录下，所以 `--config` 起的另一个实例独立成锁。`doctor` 的探活也复用这把锁：`read_status` 非阻塞地试拿一次，拿到了说明没人在跑（立刻释放并报 not-running），被挡住才去读 payload 里的 pid 和启动时间，docstring 管这叫 zero-network liveness probe，不用开端口也不用发请求。

health 端点是一个手写的 `asyncio.start_server`，对任何请求回一个 200 加 `{"status":"ok"}`。绑定失败时不致命：

```python
try:
    health_server = await asyncio.start_server(_health_handler, "127.0.0.1", port)
    console.print(f"[green]✓[/green] Health: http://127.0.0.1:{port}/health")
except OSError as exc:
    logger.warning(
        "health endpoint unavailable on 127.0.0.1:{} ({}); gateway continues without it",
        port,
        exc,
    )
```

关停顺序在 `finally` 里，注释把理由写在了代码旁边：

```python
if health_server is not None:
    health_server.close()
# Stop background producers before tearing down the scheduler
# they submit through: a cron timer firing during teardown would
# otherwise submit to an already-shut scheduler.
cron.stop()
if question_broker is not None:
    question_broker.cancel_all()  # release any turn blocked on ask_user
if gw_teardown is not None:
    await gw_teardown()
agent.stop()
await channels.stop_all()
```

顺序是「先停生产者，再拆消费者」：cron 是往调度器里投任务的后台定时器，不先停它，拆调度器的过程中一次定时触发就会往一个已经关掉的调度器提交。`question_broker.cancel_all()` 排在 teardown 前面，是为了把还卡在 `ask_user` 上的那一轮放出来，否则 teardown 会等一个永远等不到的答案。

## 六、成熟度标签：一个字段管四个展示面

这一节整节晚于代码基线，机制来自 PR #50，`76d3761` 上没有 `maturity` 字段，`channels list` 与 `channels status` 也没有那一列。放进本章是因为它是第九节那次翻车的直接结果，不讲它就讲不清那次翻车修的是什么。

远端 main 上 `ChannelSpec` 多了一个字段，docstring 定义了它的语义：

```python
    ``maturity`` names the evidence level behind the adapter, not code quality:
    ``beta`` = deterministic contract (V-C0) and security (V-S0) bundles only;
    ``live-gated`` = a live Channel gate has also passed. It is the single
    source the CLI, doctor, and onboarding read, so no surface can claim a
    higher level than the spec declares.
    """

    display_name: str
    factory: Callable[[Any], Channel]  # (config) -> Channel
    capabilities: Capabilities = field(default_factory=Capabilities)
    maturity: Maturity = "beta"
```

「不是代码质量，是证据等级」这半句就是它和普通 alpha/beta/stable 标签的全部区别。读它的地方有四处，`pico/cli/channel_commands.py` 的 list 与 status 两个表格（走同一个 `_maturity` 辅助函数）、`pico/cli/doctor_commands.py` 的已启用 channel 行、`pico/cli/onboard_commands.py` 的引导提示（后两处各有一个 `_channel_maturity`）；四处全都在 spec 缺失时显示 unknown，而不是猜一个默认值。规范文档补了一条制度：An adapter may declare `live-gated` only in the same change that records a passed live Gate run for a commit。

同一份规范还把 Beta 不声称什么列成了清单，三条：没有真实 bot 通过 Pico 收发过消息；平台配额、限流、凭证轮换、重连行为没有对着真实服务观测过；出站端点的行为没有验证过，因为所有出站断言都是对着 mock 的 SDK client 做的。三个适配器（M9）当前全部是 beta。

## 七、证据门：V-C0 与 V-LF

### V-C0：确定性契约门

`make verify-channels` 在 PR #48 落地时是一次 pytest 跑完 19 个文件的清单，写一份 `pico.channels.evidence.v1` 的报告加一份带 sha256 的日志；PR #50 把它扩成契约（V-C0）与安全隔离（V-S0）两个 bundle 分开跑、合写一份报告，报告 schema 随之升到 `.v2`（规范规定报告结构的破坏性变更用 `.v2` 后缀标记），契约清单也多了一个文件（`tests/test_config_update_channels.py`，共 20 个）。判定极严，`_classify` 要求 `passed > 0` 且 `failed`、`errors`、`skipped`、`xfailed`、`xpassed` 全为零。判定函数的 docstring 讲了为什么 skip 也算不过：A skip or an expected failure is not evidence that a Channel contract holds。第 11 章讲证据等级时引的就是这一段。

清单本身写在脚本里而不是靠目录通配，脚本内注释给的维护规则是新增确定性测试文件要在同一个变更里加进清单，否则 the gate silently stops covering it；规范文档的 Maintenance 一节重复了同一条。远端 main 上这条更狠一层，V-S0 用的是具名到函数的选择（`tests/test_channels_qq.py::test_qq_spec_import_is_cheap` 这种），注释写明理由：so a rename or a deletion fails the gate instead of quietly shrinking it。

数字用 M15：261 项契约测试，测于 PR #48；PR #50 之后增至 387 项，引用时必须带 PR 号。

### V-LF：operator-in-the-loop 的真实飞书门

V-LF 要证明的东西只有一句，规范里写死了链路：

```
Feishu event -> FeishuChannel -> Intake -> Spine -> AgentTurnRunner
  -> AgentLoop -> DeliveryHub -> ChannelOutletAdapter -> Feishu reply
```

紧跟一句边界：A mocked SDK, recorded payload, `--help` probe, or reachable endpoint never satisfies V-LF。

难点在飞书 bot 不能给自己发消息，所以入站刺激没法自动化。设计上的处理是把人当成刺激源，其余全部自动化：环境隔离、gateway 生命周期、日志观测、回执校验、重启编排、证据分级、脱敏都归 harness。每个阶段打印一条指令，然后轮询可观测结果。

入站回复那个阶段的断言设计值得单独拆开。操作者被指示发送的消息是 `ping <nonce> -- reply with exactly: pong-<nonce>`，nonce 由 `secrets.token_hex(4)` 现场生成，每次运行都不同。只看日志回执有个漏洞：accepted 和 sent 两条回执只能证明「收到了、发出去了」，证明不了中间那段真的过了模型，一个把入站原样回声的假 agent 也能凑齐两条回执。所以测试在拿到两条回执之后，还会在 30 秒窗口里轮询一次性 home 下的会话 JSONL，找 `pong-<nonce>` 有没有真的出现；三个观测点各卡一段链路，accepted 卡入站、sent 卡出站、nonce 回显卡中间的 agent loop，缺任何一个都记 inconclusive。出站媒体阶段（media_out）的探针同样自带可验证性：一张 1x1 透明 PNG 以 base64 常量写死在测试文件里，harness 把它写进一次性 workspace，指示操作者让 bot 用 message 工具把这个文件发回来，然后等 `Feishu message sent: msg_type=image` 这条精确到消息类型的回执。

刺激没来的时候算什么，是这个设计里最要紧的一行：

```python
def wait_marker(self, pattern: str, *, offset: int, timeout: float | None = None) -> str:
    deadline = time.monotonic() + (timeout if timeout is not None else _phase_timeout())
    while time.monotonic() < deadline:
        text = self.log_text(offset)
        match = re.search(pattern, text)
        if match:
            return match.group(0)
        time.sleep(1)
    raise TimeoutError(f"inconclusive: no match for {pattern!r} within timeout")
```

默认单阶段超时 240 秒，超时抛出的字符串里带着 `inconclusive` 前缀，上层把它记成这个阶段的状态。汇总函数不给任何模糊状态开后门：

```python
def aggregate(checks: dict[str, dict], *, credentials_present: bool, required: bool) -> str:
    if not credentials_present:
        return "failed" if required else "skipped"
    for name in REQUIRED_CHECKS:
        if checks.get(name, {}).get("status") != "passed":
            return "failed"
    return "passed"
```

五个必需阶段（`gateway_boot`、`inbound_reply_text`、`attachment_inbound`、`media_out`、`cron_restart_exactly_once`）里但凡有一个不是 `passed`，整个门就是 `failed`。`make verify-live-feishu` 会设 `PICO_LIVE_FEISHU_REQUIRED=1`，此时缺凭证也是失败而不是跳过；不设这个变量的临时 `pytest -m real_channel` 才把缺凭证当普通 skip。第六个阶段 `allowlist_negative_live` 需要第二个飞书账号（用 `PICO_LIVE_FEISHU_SECOND_ACTOR=1` 显式声明有），没有就记 `skipped`，理由字符串固定是 `second_account_unavailable`，不拖垮必需模式，同时在报告的 criteria 里被降级标成 `deterministic`，指向 V-C0 里对应的确定性覆盖。

隔离做得比想象中彻底：harness 在临时目录下造一个一次性的 `PICO_HOME`，里面的 `config.json` 是 0600 权限，只开飞书一个 channel，`allow_from` 只放操作者一个 open_id，`group_policy` 设成 `mention`，还顺手关掉 EverOS 记忆插件、SkillForge 和 TokenWise，把变量压到最少。gateway、cron 存储、session 存储、媒体目录、日志全在这个 home 下，操作者真实的 `~/.pico` 一次都不读不写。设了 `PICO_WHEEL` 就把 wheel 装进一个新建虚拟环境跑装出来的 `pico`，否则跑 checkout，报告里对应记 `runtime_source` 为 `installed_wheel` 或 `checkout`。

cron 那个阶段的设计单独值得讲，因为它绕开了一个陷阱。claim 有 30 分钟 TTL（`pico/proactive_engine/schedulers/cron/service.py` 里的 `_CLAIM_TTL_MS = 30 * 60 * 1000`），一个执行到一半被杀掉的任务在 TTL 内不可重领，所以「执行中杀进程」这个测法会得到假阴性。实际做法是把一次性任务定在 90 秒后触发，然后在触发时间之前把 gateway A 停掉：先数 A 的日志段里零次执行，再起 gateway B，断言 B 的日志段里恰好一次执行、一次发送回执，并且任务从 `jobs.json` 里消失了，三个条件合成 exactly once。测试里还加了一道防呆，如果关停结束时离触发时间不足 15 秒，直接记 `infrastructure_failure` 而不是硬跑，理由是关停窗口和触发窗口重叠了，这一次的结论不可信。

### 三层脱敏

写进 `.pico/evidence/feishu/` 的东西过三道：

```python
def redact_text(text: str) -> str:
    """Replace platform identifiers with stable digests and strip secrets.

    Applied to every byte that leaves the disposable home; secrets are
    removed even though they are never expected to appear."""
    for name in _SECRET_ENV:
        value = os.environ.get(name, "")
        if value:
            text = text.replace(value, "[redacted-secret]")
    identifiers = [os.environ.get("PICO_LIVE_FEISHU_APP_ID", ""), os.environ.get("PICO_LIVE_FEISHU_OPERATOR_ID", "")]
    for value in identifiers:
        if value:
            text = text.replace(value, f"id:{_digest(value)}")
    text = _ID_PATTERN.sub(lambda m: f"{m.group(1)}sha:{_digest(m.group(0))}", text)
    text = _APP_ID_PATTERN.sub(lambda m: f"cli_sha:{_digest(m.group(0))}", text)
    return text
```

第一层在这个函数之前：`excerpt_lines` 用十条回执标记做白名单，只有匹配上 `Feishu inbound accepted:`、`Feishu message sent:`、`Cron: executing job` 这类前缀的行才会被摘出来，消息正文压根没有机会进入候选集。第二层是上面这个函数里的密钥替换和 id 摘要（`ou_` / `oc_` / `om_` 开头的平台 id 和 `cli_` 开头的 app id 都换成 `sha256[:12]`）。第三层是原始 gateway 日志留在一次性 home 里，随 home 一起删掉，只有脱敏后的摘录进证据目录，每份带自己的 sha256。nonce 是否被回显只记一个布尔值，不记回显的内容。

### 这道门至今没有 passed 的运行

harness 完整落地在 PR #48（晚于代码基线、在第一轮证据基线内），到现在没有产出过一次 `passed` 的 V-LF 报告。`docs/project-status.md` 的当前 P0 blocker 仍然要求 commit-bound 的真实 inbound/outbound、reconnect、attachment、`MediaOut` 和重启后 Cron tracer bullet，归属 Issue #21，未关。数字口径表里 M10 是这道门的占位符，等真实运行落地才有值。

代码存在不等于能力生效，这一节就是本教程里这句话最贵的实例：一个 292 行的 driver 加一个 456 行的 live 测试，把除了「人发一条消息」以外的一切都自动化了，而缺的正好是那条消息。

## 八、取舍：为什么不做 X

**为什么不做 webhook，只用长连接？** 三个适配器全部走 WebSocket 长连接，飞书那个类的 docstring 写明了动机：no public IP / webhook。这对个人部署是决定性的，不需要公网地址、不需要反代、不需要证书。代价是重连要自己管，飞书那条 supervisor 是固定 5 秒退避的死循环，QQ 也是 5 秒，都没有做指数退避和抖动。

**为什么不做流式回复？** `Capabilities.streaming` 这个位存在，`SupportsStreaming` 协议也存在，但三个适配器全部声明为 False，`ChannelOutletAdapter` 直接把 `StreamDelta` 吃掉。IM 平台的流式要靠编辑已发消息实现，每个平台的编辑接口、频率限制、消息类型限制都不一样，收益是打字机效果，成本是三份平台特化代码。`Capabilities` 的 docstring 里有一条更普适的规矩管着这类字段：Only capabilities with a real consumer live here，`media` 和 `reactions` 就是因为没有消费者被拿掉的。

**为什么发送错误分成两类而不是统一重试？** `channels/errors.py` 定义了 `transient_network`，适配器只对网络类失败（超时、连接断开、WebSocket 关闭、5xx）重新抛出交给上层退避，对 4xx、坏载荷、鉴权失败一律吞掉并记日志。模块 docstring 给的理由是重试永久性失败只会重复失败或者产生重复副作用。这里有一处文档腐化要如实标：这份 docstring 和 QQ 适配器 151 行的注释都写着 `manager._send_with_retry`，而 `ChannelManager` 里已经没有这个方法了，退避实际在 `DeliveryHub` 的 outlet worker 上。行为是对的，注释指错了地方。

**为什么 QQ 的附件只到元数据为止？** 三个平台在媒体上并不对齐。飞书和 WeCom 的 SDK 都暴露下载调用，入站附件能落盘；botpy 没有为那个短时效的附件 URL 提供下载辅助函数，规范文档写明 the bytes are never fetched，所以 QQ 的入站媒体只剩标签。出站同样受限，QQ 在用的回复端点只带 markdown 文本，发不了文件；基线上的 `QQChannel.send` 对 `media` 参数是静默忽略；WeCom 在基线就会给每个没发出去的文件追加一条显式的 `[Attachment not sent: <name>]`，源码注释是 surface the dropped attachments to the user instead of losing them silently，PR #50 把 QQ 也拉齐到这个做法。同一个能力缺口，一个让用户看见，一个没有，修的就是后一半。

**为什么 gateway 的 cron 只认 IM channel？** `_build_gateway_channels` 只收集已启用的 feishu / qq / wecom，不认 `tui` 和 `cli`。注释解释得很具体：TUI 里设的提醒应该在 TUI 里响，让 gateway 认领会造成它和 TUI 抢，抢到了还发不出去（gateway 没有 cli channel）。代价也写下来了，那个进程不在时没有跨进程兜底，恢复「先在原地响，原地退出后再交接」是一个被推迟的设计。

## 九、一次真实翻车：一个字段撒谎，四个界面跟着撒谎

commit `4aa70f0`，标题 fix: drop unbacked live-gated claim and harden stderr sinks。它修了两件表面无关的事，凑在一起是因为病根是同一个。

**现象一。** 飞书适配器的 `spec.py` 里声明了 `maturity="live-gated"`，而当时没有任何一次 live channel 门通过。这个字段是四个展示面的唯一来源，于是 `channels list`、`channels status`、`doctor`、引导流程四个地方一起在夸大证据。commit body 的措辞是 overstated its evidence。

**根因。** 「单一真相来源」这个设计本身是对的，它保证了没有哪个界面能声称比 spec 更高的等级；但它同时把一次误标的影响放大了四倍，而当时没有任何机制要求这个字段的值必须有一次绑定 commit 的门运行来背书。

**修法。** 代码改动是一行，`live-gated` 改回 `beta`。制度改动在规范文档里：适配器只能在「同一个变更里记录了一次针对某个 commit 的 passed live 门运行」时才允许声明 `live-gated`。测试改动是 CLI 与 doctor 的测试钉死新标签，引导流程给飞书也打上 Beta 提示，同时保留一个用模拟 maturity 驱动的 live-gated 静默契约测试，这样 `live-gated` 这条分支的行为仍然被覆盖着，将来真的通过了门可以直接切。

**边界得说清楚。** 这次错误只活在特性分支上，`4aa70f0` 从来没有单独进过主干，它和它前一个 commit 一起被 squash 成了 PR #50。所以主干历史上不存在一个声称 live-gated 的版本。抓住它的不是 CI，是合入前对着 P0 blocker 清单自查「这个声明背后有哪次运行」。

**现象二，同一个 commit。** 常驻的 stderr 日志 sink 保留了 loguru 的默认 `diagnose=True`。这意味着适配器里任何一次 `logger.exception` 都会把失败栈帧的局部变量打进终端。这不是理论风险，`pico/channels/adapters/qq/channel.py:113` 的 `logger.exception("Error handling QQ message")` 就在 `_on_message` 的兜底 except 里，那一帧的局部变量正好是整条入站消息；飞书适配器 `_download_resource_sync` 兜底 except 里的 `logger.exception("Error downloading {} {}", ...)`（工作树 321 行）在下载失败路径上，帧里带着 message_id 和 file_key。

最刺眼的是这个洞离正确写法只有三行。同一个函数里文件 sink 早就写对了，还配了注释：

```python
        # diagnose=True would annotate tracebacks with local variable values,
        # writing secrets (API tokens, etc.) into a persisted, retained file.
        backtrace=False,
        diagnose=False,
    )
    if terminal_level is not None:
        logger.add(sys.stderr, level=terminal_level)
```

作者知道这个危害，写下了理由，然后在紧接着的下一行漏了。修法是给 stderr sink 和 `_log_silence.py` 里那个静默 sink 补上同样两个参数，各加一条注释指明是同一个 hazard，再加一个终端回归测试；显式的 `PICO_CLI_DEBUG` 镜像 sink 保留 loguru 默认值，因为那是开发者主动打开的。

两件事凑一个 commit 的共同点：没有被检验的默认值同时伤害可信度和安全。第 11 章第八节也记了这次翻车，两处描述指的是同一个 commit。

## 十、怎么被验证

确定性覆盖是 V-C0 那份清单，PR #48 时 19 个文件跑在一次 pytest 里，PR #50 扩成 20 个文件、两个 bundle。密度分布（按工作树对各文件 `grep -c "def test_"` 数出）：飞书 28 个用例、WeCom 25 个、QQ 20 个、gateway spine 装配 14 个、intake 10 个，另有 allowlist、registry、manager、media、outlet、契约本身、cron 投递、CLI channel 命令各一份。数字用 M15：261 项，测于 PR #48（PR #50 后 387 项）。

几个覆盖点能看出这份清单不是凑数的：

- `test_discover_specs_is_cheap` 起一个子进程，跑完 `discover_specs()` 后断言 `sys.modules` 里没有 `botpy`、`lark_oapi`、`wecom_aibot_sdk`。SDK 懒加载这件事没法靠 review 保证，只能靠这种探针。
- `test_channels_required_marker.py` 维护一张「哪些凭证缺了适配器就会在 `start()` 里 bail」的审计表，逐条注释指向对应的适配器守卫（feishu 是 `app_id`/`app_secret`，qq 是 `app_id`/`secret`，wecom 是 `bot_id`/`secret`），再断言配置 schema 的 required 标记与它逐字相等。文件头写了维护规则：适配器改了强制什么，适配器、schema 标记、这张表要在同一个变更里一起改。
- `test_reply_to_unregistered_channel_is_dropped_not_raised`（在清单内的 `test_cli_gateway_spine.py` 里）钉住 hub 对未注册 channel 的行为是丢弃加告警而不是抛异常。

gateway 进程层还有两组测试要点名，但要说准归属：`test_gateway_refuses_second_instance` 与 `test_stop_dispatch_cancels_both_scheduler_and_subagents` 在 `tests/test_cli_gateway_commands.py`，`test_payload_readable_while_lock_held` 在 `tests/test_cli_gateway_lock.py`，这两个文件都不在 V-C0 清单里，靠保留套件（M1）覆盖。前两个分别钉单实例语义和 `/stop` 同时取消调度器与 subagent，后一个钉「持锁时 payload 仍可读」这条 Windows 特化设计。被追问「这些测试是不是都进了门」时，先分清清单内外再报测试名。

live 覆盖是 V-LF，命令 `make verify-live-feishu`，报告 schema `pico.feishu.live.evidence.v1`。当前状态：harness 在，报告没有，M10 是占位符。

再说一层没做的：CI 不跑 V-C0。`docs/project-status.md` 里 CI 的三个 job 只包含改动文件的 pre-commit、少量 Python lint 与四个测试文件、完整的前端检查，V-C0 和 V-LF 都要贡献者按 issue 手动跑并把结果绑进 PR。这条债在同一份文档里被明确记着。

## 十一、预演追问

**「用户在飞书发一条消息，到 agent 回复，整条链路怎么走？」**（链路题，4 次高频）
SDK 的 WebSocket 线程收到事件后先查运行标志，丢掉停机后仍在投递的僵尸事件，再跳回主事件循环。然后是四道闸门：按 message_id 去重、丢掉 bot 自己的消息、群消息检查是不是在叫它、查发送者 allowlist，allowlist 这一步刻意排在表情回应和媒体下载之前，被拒的人不会触发任何副作用。通过之后打一个表情表示收到，抽取内容，图片音频文件落盘，语音先试平台自带的识别再落到 Whisper，然后交给注入的 Intake。Intake 只做两件事，查权限和构造 TurnRequest，控制命令的拦截不在它这儿，因为调度器和 agent 在 gateway 那一层。gateway 的入站分发有四个分支：控制命令、待答问题、忙时注入、普通提交。turn 跑完之后回复走 spine 的 delivery hub，按来源 channel 路由到那个 channel 的 outlet，落回适配器的 send。全程有四条结构化日志回执，入站接受、重复抑制、allowlist 拒绝、发送成功，它们是 V-LF 唯一的真实观测点；说的时候要带一句，这套回执是和 V-LF harness 同一个 PR 加进来的，更早的代码在那些点位是静默的。

**「上一条还没答完又来一条怎么办？」**（失败路径题）
不排队，改成注入。gateway 的入站分发会先问调度器这条会话有没有在跑的 turn，有就用 INJECT 策略提交，请求进一个 inject 邮箱，等运行中的那一轮在工具循环的间隙把它 drain 进来并入上下文；如果那一轮到结束都没 drain，worker 会把它退回成一个普通排队 turn，不会丢。这么做是因为用户中途补的话通常是修正而不是新任务，排队等于让 agent 把错的活干完再看纠正。这个分支前面还压着一条更优先的：如果这条会话正卡在 ask_user 上等回答，用户的下一条就是答案，走 broker 解开那个挂起的工具调用。顺序反了会形成自己等自己的死结。

**「新加一个平台要改哪些地方？」**（扩展性题）
新建一个适配器包，里面两个文件，一个 19 行的 spec.py 声明显示名和一个延迟导入 SDK 的工厂，一个 channel.py 实现 start/stop/send，再在配置 schema 里加一节、在 pyproject 里加一个 extra。除此之外一处不用改，因为注册表是扫包目录得到的，channels list、status、doctor、引导流程、ChannelManager 全部走同一个发现函数，没有任何硬编码的平台名分支。这里最容易被追问的是为什么工厂要延迟导入：因为列举 channel 是个高频廉价操作，不能因为想知道有哪些 channel 就把三家 SDK 都拉进内存；这条有专门的子进程测试断言发现之后 sys.modules 里不能出现任何一个 SDK。

**「数据私密性怎么保证？」**（3 次高频，也是失分记录里被击穿过的题）
分三层说，第一层是入站的 deny by default，allowlist 空等于拒绝所有人，语义写在模块 docstring 里，理由是防止配错的 channel 意外接受全互联网；拒绝发生在任何副作用之前。第二层是证据脱敏，真实平台的验证只有白名单里的回执行会被摘出来，消息正文根本没机会进候选集，密钥被替换，平台 id 和 app id 都换成 sha256 前 12 位摘要，原始日志留在一次性目录里随目录删掉。第三层是日志本身，这里我们翻过车：常驻的终端日志 sink 保留了 loguru 默认的 diagnose，任何一次异常记录都会把失败栈帧的局部变量打进终端，而适配器的兜底 except 那一帧的局部变量正好是整条入站消息、发送者 id 和 token。同一个函数里文件 sink 早就关掉了这个开关还写了注释，紧接着的终端 sink 漏了。修完加了终端回归测试。这题我不会说「本地项目所以没问题」，接远程模型代码照样会发出去，能说的只有具体做了哪几层和哪一层是补出来的。

**「你说接入了飞书，怎么证明？」**（指标严谨性 + 真实性拷问）
我得先把证据分层，然后如实告诉你哪一层是空的。确定性那层有一道命名的门，一条命令一份带 sha256 的报告，覆盖契约、注册发现、allowlist、入站归一化与去重、出站渲染、可重试与终态错误分类、投递重试与隔离、gateway 装配、cron 投递，判定极严，skip 和 xfail 都算不通过。真实那层设计好了也实现了：一个 driver 加一个 live 测试，因为飞书 bot 不能给自己发消息，所以人是唯一的刺激源，其余全自动化，包括一次性 PICO_HOME、gateway 生命周期、日志回执轮询、重启后 cron 恰好一次的编排、三层脱敏。缺刺激超时记 inconclusive 并让整个门失败，绝不算通过。但这道门至今没有一次 passed 的运行，所以飞书在我们所有界面上都标 Beta，规范里写死了只有在同一个变更里记录了一次绑定 commit 的通过运行，才允许改成 live-gated。这一条我们自己违反过一次，在合入前被抓住改回来了。

**「这东西部署在哪儿，平时真在跑吗？」**（使用量拷问，题库里点名的零准备题型）
gateway 是一个常驻进程，`pico gateway` 起，日志按 10 MB 轮转、保留最近 7 份轮转文件（`GatewayLogConfig` 的默认值，retention 用的是 loguru 的文件份数语义，配成时长也行），本地 127.0.0.1 上有个 health 端点回 200。同一个实例只允许一个进程，用跨平台建议锁做的，锁在一个空锚文件上而不是记 pid 的 payload 上，因为 Windows 的锁是强制的，锁 payload 会让 doctor 读不到属主 pid；进程被 SIGKILL 也不会留陈旧锁，因为锁是 OS 释放的。用 `--config` 指向另一份配置就能起第二个互不干扰的实例，因为锁挂在实例数据目录下。诚实的部分是：我跑的是本机常驻，没有容器化部署证据，也没有一次绑定 commit 的真实飞书收发记录，所以「在跑」这件事目前只有我自己的使用经验，没有可复现的证据支撑。

## 口播稿

> Channel 这一层我们的判断是接入必须便宜，而声明必须昂贵。便宜指的是加一个平台只写两个文件，一个十九行的描述符声明显示名和一个延迟导入 SDK 的工厂，一个适配器实现 start/stop/send，注册表靠扫包发现，所有展示面走同一个发现函数，没有任何硬编码的平台名分支；SDK 懒加载有子进程测试断言发现之后不能把任何一家 SDK 拉进内存，一个平台的依赖缺失只禁用那一个 channel。gateway 的入站分发是四个有优先级的分支，控制命令不能被当成 turn 提交否则模型会认真回答「好的我这就停下」然后什么也不停，待答的 ask_user 优先于忙，忙的时候用注入而不是排队，因为用户中途补的话通常是修正。昂贵指的是成熟度标签由证据决定，Beta 只代表确定性契约通过，要改成 live-gated 必须在同一个变更里记录一次绑定 commit 的通过运行。真实飞书那道门我们设计了 operator-in-the-loop，人只负责发一条消息，环境隔离、重启后 cron 恰好一次、三层脱敏、结果分级全自动化，缺刺激超时记 inconclusive 而不是假通过。这道门到今天没有一次通过的运行，所以飞书在我们所有界面上标的是 Beta。我们自己违反过这条一次，一个字段误标 live-gated 让四个展示面一起夸大证据，在合入前被抓住改了回来，同一个提交还修掉了终端日志把入站消息体打出来的问题。

## 复习路径（10 分钟）

1. 默写 `ChannelSpec` 的三个字段和 `factory` 延迟导入的动机，说得出「加一个平台改哪两个文件、不用改哪五个地方」。
2. 背入站四分支的顺序和每条挡的坏结果，尤其讲得清 ask_user 待答为什么必须排在忙检查前面。
3. 记住关停顺序的理由一句话：先停生产者（cron）再拆消费者（scheduler），否则关停途中的一次定时触发会提交给已关闭的调度器。
4. 记住三句可以直接引用的原文：mocked SDK 不满足 V-LF、skip 不是契约成立的证据、maturity 是证据等级不是代码质量。
5. 把三个诚实边界说顺：V-LF harness 已落地但零次 passed（M10 仍是占位符）；基线上的隔离有两个破口，非 ImportError 的工厂异常会冒出去、空 allowlist 会 SystemExit 掉整个 gateway，都是 PR #50 修的；四条日志回执随 PR #48 才存在，基线代码在那些点位是静默的。
