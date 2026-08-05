# 01 Spine 与 Turn 调度：排序、取消、交付的骨干

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。

读完这一篇，你应该能回答：

- 并发场景下 agent 系统最常见的三种事故，分别被哪个机制堵住
- Lane 里两个 asyncio task 的分工，取消为什么永远打其中一个
- BusyPolicy 三种策略在代码里怎么分流，INJECT 从进门到合并的完整时间线
- `handle.result()` 的三层语义，为什么它永不抛 turn 的异常
- 投递失败时系统怎么办，哪些局限是明写认账的
- 单线程事件循环里为什么还要抠原子性，哪几段代码靠「无 await」保命

## 一、问题：并发一来，三种事故

第 00 章讲过朴素多入口 agent 的六个坑，这一章把其中三个放大成具体事故。

事故一：乱序。同一个群连发两条消息，两个协程各跑一轮，交叉往同一份历史里写。修复方案里最常见的是一把全局锁，结果换来另一个事故：一个人卡住全员。这不是假想敌，这个仓库自己走过这条路，`test_spine_scheduler.py` 里 `test_different_conversations_run_concurrently` 的注释写着 unlike the old global lock，专门防止有人把并行会话改回全局串行。

事故二：停不下来。用户说停，你手里只有一堆 `asyncio.create_task` 出去的任务，不知道哪个属于这个会话；`task.cancel()` 下去，异常在哪被吞、回复发到一半怎么办，全是未定义行为。

事故三：挂死。调用方 `await` 一个 future 等结果，而失败路径上有一个分支忘了 resolve 它。这种 bug 不报错，就是永远等着。Spine 把对它的承诺直接写进了 `Scheduler.shutdown` 的 docstring：Every turn's future resolves on one of the four exit paths，so result() never hangs。

这三种事故有个共同根源：排序、取消、结果交付这三件事没有明确的所有者。Spine 的设计就是给它们各立一个所有者：排序归 Lane，取消归 Lane 的三个取消入口，结果归 worker（future 的唯一 resolver），平台投递归 DeliveryHub。而且立得非常小：六个业务模块加一个再导出入口 `__init__.py` 合计 1009 行（scheduler.py 462、delivery.py 252、events.py 119、runner.py 41、turn.py 40、message.py 37、`__init__.py` 58，`wc -l` 实测），配了 2124 行测试，测试和实现的比例大约 2.1 比 1。

## 二、前一代的答案：广播总线，和它留下的疤

这个仓库的上一代架构走的是当时最常见的路线：一条 pub/sub 消息总线，入站消息广播出去，一个叫 drainer 的组件订阅并分发。总线本身已经被移除，但代码里留着几处疤痕注释，拼起来能还原它的问题。

`pico/cli/_gateway_spine.py` 里这段最有信息量：

> Adapt the hub into the gateway's EventSink, restoring the two lifecycle side effects the bus drainer's `_dispatch` had (which the plain hub sink drops): on every turn end fire the generic `on_turn_complete` callbacks, and on a non-cancelled failure deliver a user-visible error reply...

翻译过来：旧 drainer 的 `_dispatch` 一个函数里混着三类职责，控制命令处理（`/stop` 的 `_handle_stop`）、生命周期副作用（完成回调、失败回复）、异常吞噬。拆掉总线换成 submit/emit 两个口之后，这些隐式副作用必须逐个显式重建，而重建时漏了两个，事后靠 gateway 自己的 sink 补了回来。

疤痕不止这一处，每类职责的新家都留了注释指回旧总线。控制命令归了 Scheduler：`cancel_conversation` 的 docstring 自称 The spine-native equivalent of the bus drainer's per-session `_handle_stop`。异常传播归了 lane：`pico/agent/loop/main.py` 的 `run_turn` docstring 写着 run_turn does not catch sandbox-init to return an error string (the legacy direct path did; the spine surfaces it as a TurnFailed event instead)，旧路径把沙箱初始化异常吞成一个看似成功的字符串，新路径让它以 TurnFailed 事件的身份出现。迁移一条总线，最危险的不是搬功能，是清点 dispatch 函数里没人认领的隐式副作用。

`pico/spine/__init__.py` 的模块 docstring 把立场写死了：Deliberately not a broadcast bus — it replaces the dormant pub/sub `bus`。CONTEXT.md 的词条还加了两条 _Avoid_：不许把 Spine 叫 the bus，也不许把 Lane 叫 queue（Lane 是串行加取消域，不只是队列）。一个术语禁令背后是一次架构迁移的教训，面试里讲这个比讲功能列表有分量。

## 三、词汇表：六个内容事件，三个生命周期事件

先认识地址类型。`pico/spine/message.py`（37 行）只有两个纯数据类：`Source` 是消息的来源和回复地址，四个必填字段 `channel`、`chat_id`、`sender_id`、`chat_type`（dm 或 group），外加一个 `extras` 字典；`Media` 是校验过的附件。`Source` 是 frozen dataclass 但故意不可哈希，因为 `extras` 是活字典，`test_source_is_intentionally_not_hashable` 把这个属性钉成已知事实而不是意外，注释同时交代用途：Lane 用 conversation_id 字符串做键，从不用 Source 对象。

`pico/spine/events.py`（119 行）定义了全部输出词汇。内容事件六个：`Text`、`MediaOut`、`StreamDelta`、`Reasoning`、`Notice`、`ToolEvent`，统称 Deliverable。这不是一个新类型，文件末尾把关系写死：

```python
RunnerEvent = ToolEvent | Text | MediaOut | StreamDelta | Reasoning | Notice
# Same union, named for its delivery role: what the hub routes and an Outlet renders.
Deliverable = RunnerEvent
TurnEvent = TurnStarted | TurnFailed | TurnEnded | RunnerEvent
```

一个 union 两个角色名，`test_deliverable_is_the_runner_event_union_under_its_delivery_role_name` 断言 `Deliverable is RunnerEvent`。生命周期事件三个，文件里的注释头直接写着归属：

```python
# Lifecycle events — emitted by the worker, never by a runner.

@dataclass(frozen=True)
class TurnFailed:
    error: str
    cancelled: bool
    conversation_id: str | None = None

@dataclass(frozen=True)
class TurnEnded:
    usage: Usage
    latency_ms: float
    explicit_reply: bool
    conversation_id: str | None = None
    tool_calls: int = 0
    tool_failures: int = 0
```

四个结构细节值得记。生命周期事件都没有 `source` 字段，这不是遗漏：交付层按 `source.channel` 路由，没有 source 的事件结构上就进不了投递队列（`test_every_turn_event_defaults_conversation_id_to_none` 的最后一行断言三个生命周期事件连 source 属性都不存在；后面第七节回到这点）。`TurnFailed` 刻意不带 usage，`test_turn_failed_has_no_usage` 断言它的字段集恰好是 error、cancelled、conversation_id 三个。`Usage` 只有三个 int（prompt、completion、total），更富的账走 agent loop 的 usage_sink，两套口径分开。全部九个事件都是 frozen dataclass，参数化测试 `test_every_event_type_is_frozen` 逐一验证 setattr 必炸；不可变让事件可以安全地跨队列传递、被多处持有。

按规则 6 把不好看的也摆出来：这份词汇表里有几段建好没通电的管道。`NoticeKind` 四个值里 `INJECTED` 全仓零消费者（grep 只有定义那一行）；`DELIVERY_FAILED` 只在测试里出现，投递失败实际走 log 加丢弃；`StreamDelta.stream_id` 字段存在但没有生产者写、没有消费者读，hub 给 outlet 的 stream 标识传的是 `conversation_id`，它是个死字段。被问到「你们的事件模型完备吗」，这几处就是诚实答案的素材：词汇表比实现超前，超前的部分没有假装已经工作。

## 四、Lane 解剖：两个 task，一把刀

### Lane 的钥匙，和 home loop 守卫

输入侧的词汇在 `pico/spine/turn.py`：`TurnRequest` 带 `origin`（USER/CRON/SUBAGENT）、`source`、`text`、`media`、`message_id`、`conversation`、`busy` 七个字段，frozen。每个会话一条 Lane，「会话」由一个字符串键定义：`Scheduler._conversation_id` 先看请求有没有显式 `conversation` 字段，没有就退到 `f"{req.source.channel}:{req.source.chat_id}"`。旁边的注释交代了分层：按 thread 或 topic 细分会话是 channel 自己的事，channel 格式化好键再显式传进来，调度器保持 channel-agnostic。

`submit` 的第一件事是一个容易被忽略的守卫：

```python
if asyncio.get_running_loop() is not self._loop:
    # Off-loop (e.g. a channel's ws thread running its own loop) would
    # build the lane on the wrong loop — fail loud, don't bridge silently.
    raise RuntimeError("submit must be called from the scheduler's event loop")
```

比较对象是构造时存下的 `self._loop`，不是「有没有 loop 在跑」。`test_submit_from_a_different_loop_fails_fast` 的注释点名了真实场景：feishu 的 websocket 线程跑着自己的事件循环，只查 `get_running_loop()` 不会报错，比较 home loop 才拦得住。跨线程桥接是入站层的显式职责，runtime.md 写明 Intake normalizes inbound data and submits it on the Scheduler's event loop。

### 两个 task，一把刀

Lane 内部有两个 asyncio task，分工是理解取消语义的钥匙。`_worker` 串行消费 pending 队列，队列空了就退出并给 reaper 打时间戳，下一次 submit 发现它不在或已退出就重建（`submit` 尾部两行，和 DeliveryHub 的 outlet worker 同款套路）；`_run_task` 一个 turn 一个，是取消的靶子。刀永远砍 `_run_task`，不砍 `_worker`。worker 里 `create_task` 是同步创建的，注释写明意图：no await before this，so the turn is cancel-visible via `_run_task` the moment it leaves the queue，请求一出队就必须能被取消命中，不留盲区。

### submit 的三路分流

BusyPolicy 的三种策略全在 `Lane.submit` 里分流（`pico/spine/scheduler.py`，真实代码）：

```python
running = self._run_task is not None and not self._run_task.done()
if policy is BusyPolicy.INTERRUPT and running:
    # Preempt: cancel the running turn (only its task — the worker stays
    # the sole resolver of its future) and jump the interrupter to the
    # front, ahead of any APPEND backlog.
    self._run_task.cancel()
    self._enqueue(req, fut, front=True)
elif policy is BusyPolicy.INJECT and running:
    self._inject_mailbox.append((req, fut))
    return fut
else:
    self._enqueue(req, fut)
```

INTERRUPT 是同一把刀加插队：取消当前 `_run_task`，新请求 `appendleft` 到队头，排在所有 APPEND 积压前面；连按两次 INTERRUPT 是后进先出，`test_two_interrupts_run_latest_first` 断言执行序是 hang、i2、i1。INJECT 进 mailbox 后直接返回，连 worker 都不碰，因为它的目的地是正在跑的那个 turn。空闲 Lane 上的 INTERRUPT 和 INJECT 都退化成普通排队（else 分支），没有可打断或可注入的对象。

还有一条容易忽略的约束：INTERRUPT 和 INJECT 都是 USER 专属。系统来源（cron、subagent）请求这两种策略会被 `Scheduler._effective_busy` 降级成 APPEND，并记一条同时带 requested 和 applied 的日志，docstring 写明动机是让「我要求 INTERRUPT 为什么没反应」可调试；`test_non_user_interrupt_is_demoted_to_append_with_a_log` 连日志里 origin、requested、applied 三个词都断言了。后台任务没有资格打断或挤进用户的 turn。

### 一次 code review 抓出来的洞

`_enqueue` 是 pending 队列唯一的增长入口，深度到 50（`_DEPTH_WARN_THRESHOLD`）用 `==` 判一次告警，不用 flag 就实现「每次向上穿越只报一次」。这个「唯一入口」是被 review 逼出来的：早期版本里，未被 drain 的 inject 回落成 APPEND turn 时绕过了 submit，深度告警会漏数。测试文件里留着原话：the hole the reviewer caught: fallback re-append bypasses submit，配套用例 `test_inject_fallback_re_enqueue_also_triggers_the_depth_warning` 专门证明回落路径也会触发告警。修法就是把所有增长路径收进 `_enqueue`，告警的完备性靠结构收口，不靠每个调用点自觉。

### 一个 turn 的实际执行顺序

`_run_turn` 里的顺序每一处都有讲究：

1. 先取 OriginPools 信号量，然后才发 `TurnStarted`，同时置 `started` 标志。排队等槽位期间外界看不到任何事件；取消落在这个窗口里，一个事件都不发，`test_cancel_before_turnstarted_emits_no_lifecycle` 断言 `events == []`，注释写明规矩是 only pair a TurnStarted，没发开始就不发失败，不留孤儿事件。
2. `latency_ms` 的起点在 `TurnStarted` 发出之后（源码顺序是发事件、置标志、`run_start = time.monotonic()`），不含排队时间也不含等信号量的时间。口径问题，被追问「你们的延迟指标含不含排队」时答案是明确的。
3. 异常路径发 `TurnFailed` 后 `return None`；取消路径发 `TurnFailed(cancelled=True)` 后 `raise`。这个不对称是故意的：worker 靠它区分「payload 被取消」（正常，turn 自己发了终态）和「worker 自己被取消」（进程硬杀，要级联取消 payload、await 它清理完再重抛，`test_worker_self_cancellation_drains_the_payload_leaving_no_zombie` 证明不留僵尸）。
4. 被 drain 走的 inject 的 future 在 `finally` 里跟着宿主 turn 的结果一起 resolve，先于 `TurnEnded` 发出。
5. 发终态用 `_emit_terminal`，它把 sink 抛的异常吞掉记日志。sink 崩了不能带崩 lane worker，否则一个渲染 bug 就让整个会话失去响应；`test_terminal_sink_failure_does_not_kill_lane_worker` 让 sink 第一次就炸，断言下一个 turn 照常跑完。

### 一条时间线：INJECT 从进门到合并

用一个群聊场景把 INJECT 的生命周期串起来。设群 g1 的 Lane 空闲，用户 A、B 先后发言：

1. A 的消息进来，intake 查 `has_inflight("feishu:g1")` 为 False，按 APPEND 提交；worker 拉起，turn A 拿到 user 池槽位，发 `TurnStarted`。
2. turn A 还在跑，B 的消息进来，`has_inflight` 已是 True，intake 改用 INJECT 提交（这正是 `has_inflight` 存在的理由，docstring 原话：The inbound gate uses this to submit a mid-turn message as BusyPolicy.INJECT）。B 的请求进 `_inject_mailbox`，submit 直接返回 future。
3. turn A 在两次工具调用的间隙调 `drain()`：mailbox 被读空，B 的文本并进 A 的上下文，B 的 future 被记进 A 的 chained 列表。从 mailbox 移除这一个动作同时保证了 `/stop` 再清 mailbox 也碰不到 B，每个 future 恰好一个 resolver。
4. turn A 完成，`_run_turn` 的 `finally` 先用 A 的 outcome resolve B 的 future，然后才发 `TurnEnded`；B 的调用方 `await handle.result()` 拿到的就是宿主的结果（`test_inject_merges_into_host_and_chains_its_outcome`）。
5. 岔路一：A 到结束都没调 drain。worker 的 `finally` 把 B 回落成新的 APPEND turn 重新排队，USER 来源还会记一条 inject fell back to append 日志，消息不丢（`test_undrained_inject_falls_back_to_append_with_a_log`）。
6. 岔路二：合并前 B 反悔。`handle.cancel()` 把它从 mailbox 直接删掉、以 None resolve，宿主无感（`test_cancel_on_a_mailboxed_inject_removes_it_before_merge`）；合并之后再 cancel 是 no-op，杀不掉宿主（`test_cancel_on_a_merged_inject_is_noop_and_host_survives`）。

runner 侧对应的接口是 `Drain` 类型别名（`pico/spine/runner.py`），注释写明最小合法实现可以永不 drain，一切 inject 都走回落路径；合并是优化，不合并是兜底，两条路都不丢消息。

### emit 边界的两件事

runner 拿到的 `emit` 是包过的：类型守卫拒绝生命周期事件（用 `get_args(RunnerEvent)` 展开的元组做 isinstance，注释写明是防止类型检查器把守卫标成不可达后被人删掉，这是本仓库没有静态检查器时的唯一执法点）；然后给事件盖章，source 和 conversation_id 只在为 None 时补，runner 显式给的值不覆盖。only-None 语义两条各有测试（`test_emit_stamps_source_when_absent_and_preserves_explicit`、`test_emit_stamps_conversation_id_and_preserves_explicit`）。

## 五、取消：三个入口，一条链

| 入口 | 粒度 | 场景 |
|---|---|---|
| `TurnHandle.cancel()` | 单个 turn | 调用方撤回自己那次请求 |
| `Scheduler.cancel_conversation(cid)` | 整条 Lane | 用户在群里发 `/stop` |
| `Scheduler.shutdown(grace)` | 全局 | 进程关停 |

`cancel_turn` 按 turn 的三种状态各走一条路：还在排队，直接从队列删掉、future 以 None resolve，这个 turn 从未跑过，不发任何事件；还在 inject mailbox 里，同样直接删掉并以 None resolve；正在跑，只 `task.cancel()`，绝不碰 future。future 由 worker 唯一解决，这条纪律的反面就是开头的事故三和一个更隐蔽的坑：对同一个 future 双重 `set_result` 抛 `InvalidStateError`。`test_stop_after_drain_resolves_a_chained_inject_exactly_once` 的注释把这个危险直接写成了标题式说明。

调用方手里的东西小到可以整段贴出来（`pico/spine/scheduler.py`，真实代码）：

```python
class TurnHandle:
    """Returned by submit; the caller's view of one turn."""

    def __init__(self, lane: Lane, fut: asyncio.Future):
        self._lane = lane
        self._fut = fut

    async def result(self) -> TurnOutcome | None:
        return await asyncio.shield(self._fut)

    def cancel(self) -> None:
        self._lane.cancel_turn(self._fut)
```

`result()` 的三层语义：成功拿到 `TurnOutcome`；失败拿到 None，错误详情在 `TurnFailed` 事件里；取消同样拿到 None，区分靠 `TurnFailed.cancelled`。它永不抛 turn 的异常，原因在实现里：worker 只调 `set_result`，整个 spine 没有一处 `set_exception`，失败被压成 None 加一条结构化事件。shield 是另一层保护：等结果的协程自己被取消时，它收到 `CancelledError`，但 turn 的 future 不受影响、turn 继续跑（`test_cancelled_result_waiter_does_not_cancel_shared_turn_future`）；想杀 turn 必须走 handle 或会话取消。TUI 的 `turn.cancel` 把这套语义用到了极致：cancel 之后还要 `await handle.result()` 直到 turn 真正解开才返回，docstring 写明防的是 the next `turn.send` cannot race a half-unwound turn into a phantom -32003。

优雅关停是四相：封印（submit 快速失败，抛 `SchedulerDrainingError`）、清空未启动的工作（pending 队列和 inject mailbox 全部以 None resolve）、给在飞 turn 一个宽限窗口、级联取消幸存者并 await 它们真正退完。封印和清空之间刻意没有 await：否则宽限期里 turn 正常结束时，worker 的 finally 会把 mailbox 里的 inject 回落成新 turn，凭空复活一个该死的请求。清空和宽限之间还夹着一步，把 reaper task 取消并 await 干净，shutdown 不留后台任务。顺便交代一个现实：三个 host 的 teardown 全部传 `grace=0.0`（`pico/cli/_repl_spine.py`、`pico/cli/_gateway_spine.py`、`pico/tui_rpc/spine.py` 各自的 teardown），宽限窗口在生产里从未真正生效过，只有测试用非零值。

## 六、OriginPools：没有 else 分支的信号量

```python
def for_origin(self, origin: Origin) -> asyncio.Semaphore:
    if origin is Origin.USER:
        return self._user
    if origin in _SYSTEM_ORIGINS:
        return self._system
    # fail-loud: a new origin must consciously choose a pool, not be
    # silently funnelled into the system pool by a fallback.
    raise ValueError(f"no pool mapping for origin {origin!r}")
```

两把独立信号量，无全局上限、不互借；新增一种 Origin 不会被兜底逻辑静默塞进某个池，会在运行时炸。独立性两个方向各有测试：系统池被占满，用户 turn 照跑（`test_user_pool_is_independent_of_a_full_system_pool`）；用户池满，系统池再闲也不外借，用户 turn 只等自己的槽（`test_no_cross_pool_borrow`）。旁边的常量注释澄清一个易错点：`_SYSTEM_ORIGINS` 里的 SUBAGENT 指的是子代理结果回注主会话的那个 turn，子代理本体的执行在 SubagentManager 自己的闸门后面，不占这里的槽。

三个 host 的池子尺寸都在各自 build 函数的默认参数里：

| host | user 池 | system 池 | 出处 |
|---|---|---|---|
| REPL | 1 | 1 | `build_repl`，`pico/cli/_repl_spine.py` |
| TUI | 1 | 1 | `build_tui`，`pico/tui_rpc/spine.py` |
| Gateway | 4 | 2 | `build_gateway`，`pico/cli/_gateway_spine.py` |

Gateway 敢把 user 池开到 4，代码注释里写了前提：user>1 is safe now that per-turn tool state (message routing, context) is turn-local。反着读就是一段历史：工具状态曾经是全局的，并发用户 turn 会互相覆盖回复目标。这类「注释里的前提条件」是面试讲并发安全时最扎实的素材，它说明你知道安全不是天生的，是某次改造之后才成立的。

## 七、DeliveryHub：交付的七个决定

每个 outlet 一条 `maxsize=100` 的队列加一个常驻 worker，这是骨架；有意思的在细节决定上。

**重试有界，耗尽即丢。** 4 次尝试、3 次 sleep（1、2、4 秒，`_SEND_MAX_RETRIES=3`、`_RETRY_BASE_DELAY=1.0` 翻倍），最后一次失败不再等待，记一条 error 后丢弃；error 里带 channel、事件类型、原因三个字段，测试连这三个字段都断言（`test_exhausted_retries_log_an_error_and_drop`）。文档明写认账：出站队列不持久化，投递失败不回滚已完成的 turn（runtime.md：delivery failure is not currently a transactional Turn failure）。这是设计选择：turn 的产出已进会话记录，交付层的责任边界到「尽力送达」为止。

**重试是串行阻塞的。** worker 单线，一条消息重试满 7 秒期间，同 channel 后面的消息都排着。这个看似缺点的行为被 `test_per_outlet_serial_holds_across_a_retry` 固定成了契约：保序优先于吞吐。

**背压按 channel 隔离。** 队列满只堵自己这个 channel 的生产者，飞书抖动不影响 CLI 出字（`test_per_outlet_backpressure_isolates_channels` 把 maxsize 缩到 1 演示这一点）。

**worker 死了自己会活过来。** `_enqueue` 在 worker 不存在或 `done()` 时重建，注释解释为什么 `done()` 也要查：常驻 worker 死了没人消费队列，这个 channel 的发送方会静默死锁；`test_a_dead_worker_self_heals_on_next_enqueue` 模拟 worker 被杀后下一条消息把它救活。`register` 则相反，注册后不热替换，活 worker 启动时已捕获自己的 outlet，注释写明 register-once, at startup。

**流式零聚合。** hub 对 StreamDelta 逐条转发，能不能收 chunk 由双重门禁决定：结构上实现 `SupportsStreaming` 且能力声明 `streaming=True`，缺一个就静默吃掉。「吃掉」在 Outlet 协议里是正常语义，docstring 写明 Eating is not failure，只有真正的传输错误才 raise、才触发重试。流式收尾靠一个内部标记：生命周期事件没有 source 上不了投递队列，`close_stream` 就往队列里放一个 `_StreamClose` 标记，让 done=True 的收尾 chunk 排在最后一条 delta 之后；同一会话下一个 turn 重新开流也干净，`test_a_stream_reopens_cleanly_for_the_next_turn` 同时断言两张流状态表都被清空。

**`post()` 和 `dispatch()` 是同一份实现的两个名字。** 唯一差别是语义：dispatch 给 turn 产出的事件，post 给不来自 turn 的事件，全仓唯一生产调用点是 cron 多目标广播（`pico/cli/_cron_handler.py`）。可以讨论这算文档化的 API 分层还是多余的间接层；我的判断是前者，因为它让「谁在往交付层塞东西」grep 一下就清楚。

**渲染屏障就是 `Queue.join()`。** `wait_idle` 的全部正确性押在「每个出队的 item 都有对应 task_done」上，所以 worker 循环和 drain 里各有一个看似多余的 `task_done()` 调用，注释都指向同一句话：join 不能挂。

诚实清单同样有：`close_stream` 的生产调用者只有 TUI 一处（sink 的 `_finish` 在每个 TurnEnded/TurnFailed 上都调它，`pico/tui_rpc/spine.py`），channel 侧没有接流，runtime.md 写明 channel 只收最终的 Text 和 MediaOut，不收 token 流；`make_hub_sink` 的 docstring 说 REPL 和 gateway 共用它，对了一半，REPL 的 `_make_cli_sink` 内部确实包着它做 deliverable 路由，gateway 的 `_make_gateway_sink` 是独立实现并没有用它，docstring 的 gateway 半句已陈旧。

## 八、reaper：不加锁的原子性

Lane 空闲 300 秒（`_DEFAULT_IDLE_TTL`）被回收，60 秒（`_SWEEP_INTERVAL`）扫一次。reaper 由第一次 submit 顺手拉起，和 lane worker 同款的懒启动；没有 lane 时自行退出，下一次 submit 再拉起；shutdown 显式取消并 await 它。有一条测试专门证明「活的 reaper 真的会扫」而不只是存在（`test_running_reaper_actually_sweeps_and_reaps_an_idle_lane` 把间隔缩到 0.01 秒等真实回收发生）。

有个必须答对的问题：正在跑的 Lane 会不会被误回收？不会，而且靠的是结构而不是锁，`_sweep` 的 docstring 把机制说透了：

> Synchronous and await-free, so it cannot interleave with the equally synchronous submit: a request can never vanish into a lane being reaped — submit runs either wholly before (lane active, skipped) or wholly after (a fresh lane is built). The atomicity is structural, not locked.

submit 和 `_sweep` 都是同步无 await 的函数，在单线程事件循环里天然互斥。配合两条时钟纪律：`_idle_since` 只在 worker 退出循环后落值（worker 活着时是 None，reaper 跳过；`test_sweep_does_not_reap_a_lane_with_an_inflight_turn` 用 `now=1e9` 的远未来时间戳证明活跃 Lane 永不被扫）；submit 第一件事清掉它。worker 退出处的注释还标了双向竞态：队列检查和 return 之间不能有 await，否则一个赶在退出瞬间的 submit 会丢（lost-wakeup）。

回收后的两条语义有测试钉着：reap 后再 submit 重建 Lane 不丢请求（`test_reap_then_resubmit_rebuilds_lane_without_losing_the_request`）；拿着已回收 Lane 的 handle 去 cancel 是 no-op（`test_cancel_on_a_reaped_lanes_handle_is_a_noop`）。

## 九、取舍：为什么不做 X

**为什么不是广播总线？** 第二节的疤痕就是答案：总线把控制、副作用、异常处理混进一个 dispatch，替换它的代价（漏掉两个副作用、事后补）都被记录在案。submit/emit 两个口的形状让每类职责有唯一入口。

**为什么 future 只能由 worker 解决？** 双重 resolve 是 `InvalidStateError`，单一 resolver 是唯一防线。cancel_turn 宁可在三种状态里各写一条路，也不给任何第二方 set_result 的机会。

**为什么队列没有硬上限？** runtime.md 明写：The queue has no hard capacity... sustained submission can grow that Lane's memory use。选择了深度 50 告警而不是拒绝，理由是消息丢弃比内存增长更不可接受；上限留给了外层（channel 白名单、池并发）。这是已认账的风险，不是疏忽。

**为什么投递失败不回滚 turn？** turn 的产出在会话记录里已经是事实，回滚意味着「用户没看到就等于没发生」，那会让会话记录和记忆都跟着说谎。交付失败是交付层的失败，记录在案，不改写历史。

**为什么 submit 不做跨线程桥接？** 注释原话 fail loud, don't bridge silently：静默桥接会把 Lane 建在错误的事件循环上，bug 以「事件散落两个 loop」这种最难查的形态出现。桥接责任显式归入站层，调度器只认 home loop。

## 十、一次真实翻车

d9acb25（PR #43，Closes #17）。这个 PR 横跨三个 host，落到 spine 上只有 7 行（`git show d9acb25 --numstat -- pico/spine/` 实测）：events.py 加 3 行（`TurnEnded` 的 `tool_calls`、`tool_failures`，`ToolEvent` 的 `failed`），runner.py 加 2 行（`TurnOutcome` 的同名计数），scheduler.py 加 2 行（worker 把计数拷进 TurnEnded，`test_worker_copies_tool_counts_to_turn_ended` 钉住）。改动小，背景不小：在此之前，工具执行失败被转成一段普通文本塞回模型，从 spine 的视角看，这个 turn 是「成功完成」的。PR 描述的 Risk 段写得直白：

> The primary risk is stricter failure propagation changing callers that treated Tool error text as a successful string.

同一个主题一天里修了两次：PR #45（b303d1d）只比它晚一个小时合入，又给 `TurnOutcome` 加了 `memory_hits`、`injected_skill_ids`、`context_path`、`context_fallback_reason`、`skill_source_failures` 五个字段（runner.py 再加 5 行），Risk 段是 configured Memory failures now surface instead of degrading silently。两次的教训一致：失败必须以结构化字段的身份存在，混在文本里的失败等于不存在。runtime.md 里那句总结把它抬到原则层：a Turn, a platform delivery, a persisted transcript, and a long-term Memory update cannot be represented by one Boolean。

测试侧还有一个小翻车值得带一句：早期测试用的假 sink 没有 await，掩盖了 setup 窗口的取消竞态，换成会 await 的 sink 才暴露出来，`test_cancel_during_setup_window_stops_the_turn` 的注释留了原话 Earlier no-await fakes hid this race。假替身太快，也会骗人。

## 十一、怎么被验证

8 个 `test_spine_*.py` 共 2124 行，对 1009 行实现；`uv run pytest` 跑这 8 个文件是 145 passed，0.54 秒（本教程写作时在工作树实测），全部在保留确定性套件里（M1），不依赖模型。分工如下：

| 文件 | 行数 | 守什么 |
|---|---|---|
| test_spine_scheduler.py | 665 | Scheduler：分流、降级、reaper、shutdown、inject 全生命周期 |
| test_spine_scheduler_lane.py | 509 | Lane：FIFO、emit 盖章、各窗口取消、worker 级联 |
| test_spine_delivery.py | 449 | hub：路由、重试、背压、流式、渲染屏障 |
| test_spine_events.py | 186 | 词汇表：字段集、frozen、union 成员 |
| test_spine_runner.py | 109 | TurnRunner 协议与 TurnOutcome 字段集 |
| test_spine_turn.py | 78 | TurnRequest 与两个枚举的封闭性 |
| test_spine_message.py | 65 | Source/Media 的值对象语义 |
| test_spine_scheduler_pools.py | 63 | 双池独立、不外借、fail-loud |

挑几个最能说明设计的用例：TurnStarted 之前被取消必须零事件；emit 守卫在运行时拒绝生命周期事件；两次 INTERRUPT 后进先出；已合并 inject 的 cancel 杀不掉宿主 turn；drain 之后 `/stop` 让链式 inject 恰好 resolve 一次；投递重试期间同 channel 严格保序；wait_idle 在事件被丢弃时也不挂（对应测试名前几节都已给出）。枚举的封闭性也有测试：`Origin("system")` 必须抛错，三个值就是三个值（`test_origin_is_closed_three_value_enum_without_system`）。

一条边界要交代：证据基线 main `b65f962` 相对代码基线在 spine 的调度与投递上有约 166 行 diff（口径见 metrics-ledger 顶部对照表），本章全部代码描述以工作树 `76d3761` 为准，读 main 最新代码时可能遇到细节出入。

## 十二、预演追问

**「怎么保证同一会话的消息不乱序？」**
每个会话一条 Lane，一次只跑一个 turn，队列先进先出；worker 是唯一消费者，历史写入天然串行。跨会话是并行的，一条 Lane 卡住不影响别的会话。想插队有明确的策略位：INTERRUPT 取消当前并排到队头，INJECT 不打断、在工具循环间隙合并进当前 turn。

**「用户说停，怎么停？停到什么粒度？」**
三个粒度：单个 turn 走 handle.cancel，排队中直接删掉且零事件，运行中取消它的 task；整个会话走 cancel_conversation，对应聊天里的 /stop，清队列、清 mailbox、取消在飞；全局走 shutdown 四相，封印、清空、宽限、级联。有两个细节容易被追问：等结果的协程被取消不会杀 turn，因为 future 是 shield 过的；被取消的 turn 结果是 None 不是异常，区分取消和失败要看 TurnFailed 事件的 cancelled 标志。

**「会话正忙又来消息怎么办？」**
默认排队。聊天平台配的是 INJECT：消息进 Lane 的 mailbox，正在跑的 turn 在两次迭代之间把它 drain 进上下文合并处理；如果这个 turn 到结束都没来得及 drain，worker 兜底把它回落成一个新的排队 turn，消息不会丢。合并进宿主的 inject 共享宿主的结果，它自己的 handle 也会被 resolve 恰好一次。

**「投递失败会丢消息吗？」**
会，而且是明写认账的边界：重试 3 次退避后记 error 丢弃，出站队列不持久化。但要分清丢的是什么：丢的是这一次的平台投递，turn 本身的产出已经在会话 JSONL 里，记忆和 trace 都在。为什么不回滚 turn：投递失败不该改写「模型确实说过什么」的历史。这也是为什么文档强调一个 turn 的成败不能用一个布尔值表示，执行、投递、落盘、记忆是四个独立的成败位。

**「为什么不用现成的消息队列或 pub/sub？」**
这个系统的前一代就是 pub/sub 总线，被替换是有案可查的：总线的 dispatcher 把控制命令、生命周期副作用、异常吞噬混在一处，替换成 submit/emit 两个口时漏掉两个隐式副作用，事后补的代码和注释都在。需要的语义是「每会话串行加取消域加单一结果」，这不是广播模型的强项；外部 MQ 引入的持久化和投递保证，恰好是这里刻意不要的（进程内、低延迟、失败显式）。

**「都跑在一个线程的事件循环里，你们还需要锁吗？」**
不需要锁，但要遵守一条比锁更苛刻的纪律：想原子的临界区必须同步无 await。asyncio 的交错只发生在 await 点，两个纯同步函数天然互斥，submit 和 _sweep 就是这么做到「回收和提交不加锁也不打架」的。反过来，原子段落里混进一个 await 就全毁，代码里有两处专门防这个：worker 退出前查队列到 return 之间不能有 await，否则赶在退出瞬间的 submit 会丢，注释标着 lost-wakeup；shutdown 的封印和清空之间不能有 await，否则宽限期里 inject 会被回落复活。锁被换成了对每个 await 点位置的审查。

## 口播稿

> Spine 是全系统唯一的执行骨干，一个入口一个出口：submit 收 TurnRequest，emit 吐类型化事件。排序靠 Lane，每个会话一条，串行执行，同时是取消域；并发靠两把互不借用的信号量，用户和系统任务各一把；交付靠每个出口一条队列一个 worker，重试有界、背压按渠道隔离。取消语义我们抠得很细：future 只能由 worker 解决一次，排队中取消零事件，运行中取消打 task 不碰 future，等结果的协程被取消也杀不了 turn。它的前身是一条 pub/sub 总线，替换时漏掉两个隐式副作用的教训，让我们把「每类职责一个唯一入口」当成了硬约束。整个骨干一千行实现配两千行测试，全部确定性，不碰模型。我最喜欢的一个细节是清扫器的原子性：submit 和 sweep 都是同步无 await 的函数，在事件循环里结构性互斥，不需要锁。

## 复习路径（10 分钟）

1. 把三种事故对到三个所有者：乱序对 Lane，停不下来对取消三入口，挂死对单一 resolver。
2. 默写 submit 三路分流的行为差异，重点是 INTERRUPT 插队头、INJECT 进 mailbox 不碰 worker；再把 INJECT 时间线的两条岔路（回落、合并前自取消）走一遍。
3. 背下 _run_turn 的两条口径：latency 起点在 TurnStarted 之后不含排队，信号量先于 TurnStarted。
4. 讲得出 d9acb25 的故事：工具失败曾是「成功的字符串」，spine 侧 7 行字段改动背后是失败必须结构化的原则。
5. 记住三个认账的局限：出站不持久化、Lane 队列无硬上限、生产 grace 全是 0。
