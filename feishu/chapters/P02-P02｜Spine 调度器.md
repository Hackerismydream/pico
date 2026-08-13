# P02｜Spine 调度器

> P01 把 Agent Loop、Scheduler 和 DeliveryHub 装进了同一个 Runtime。P02 跟着四条同时到达的请求，看调度器怎么让它们各就各位，最后谁拿到结果。

## 读前准备

只带两个概念：Turn 是 Pico 对一条请求做出的完整反应，P00 讲过，这里只是提醒；会话是一组需要保持顺序的连续消息，代码里由 `conversation_id` 标识。Spine 是所有 Turn 共用的执行主干，请求从 Scheduler 进，Agent 输出从事件出口出，本章只看入口这半边，出口那条投递链路在 P08。

> **版本说明**：本章对应 commit `6559b70851964630f4f9716ecf6ca3b60191570b`，调度顺序、忙时策略、取消和关闭行为都以这份 `main` 源码为准；仓库更新后以你本地代码为准。

## 一条长任务和三个赶来的

小林在飞书里让 Pico 改一组测试，这活儿要反复读文件、改代码、跑命令，大概二十秒。结果第二秒就热闹了，小林自己又补了一句"只改 Python 文件"，同事发来一条"这个报错啥意思"，一条定时任务也正好到点，四条请求同时挤到了调度器门口。

最省事的办法是一锅烩，一条总队列先来后到，可同事的提问就得排在改测试后面，为了一个报错干等二十秒；或者干脆全开，四条一起跑，小林的两条消息又会同时动同一份文件，一个会话的上下文是共享的，两个 Turn 同时在改它，谁改完都说不清。两个办法都不行，原因其实是同一个，它们想用一个机制管两件不同的事：顺序和容量。顺序是同一个会话里消息的先后，容量是系统同时能扛几个任务，这两件事得分开管。

## 顺序和容量，得分开管

Pico 就把它们分开了，每件事一个机制：每个会话一条 Lane，负责本会话的先后；所有 Lane 共用两组并发额度，负责全局同时能跑几个。A1 和 A2 能不能同时跑，看 Lane；B1 能不能进，看额度。

先看 Lane。每个会话一条，Lane 内部是一个串行 worker，一次只从队列取一条 Turn，等它进入终态再取下一条，所以同一个会话里的消息永远按先后顺序走。A1、A2 同属 Lane A，必须按顺序；B1 在 Lane B，数据结构上就不等 A1，可以直接开始。为什么非串不可？因为同一个会话的上下文是共享的，Session 文件、工作区目录都是这一份，两条 Turn 并行改它，结果就说不清了，串行是保底，先把"一个会话同时只有一条在跑"钉死，剩下的并行空间再靠 Lane 之间的独立性去挖。

再看额度。不同 Lane 可以并行，不代表所有 Turn 都能立刻进 Runner，每条 Turn 轮到队首后，还要根据来源取额度：

| 请求来源 | 使用的额度 |
|-|-|
| USER（用户请求） | user pool |
| CRON（定时任务） | system pool |
| SUBAGENT 结果回注 | system pool |

额度是数量有限的，一条 Turn 要占一个额度才能进 Runner，跑完交还。两组额度互不借用，system pool 满载时，新的用户请求仍能走 user pool，代价是某一组空闲时，另一组不能临时借它的额度。为什么分两组而不是共用一组？因为用户任务和系统任务的优先级不同，用户正在等答案，定时任务不能把用户挤到门外，分池就是把这两类请求的容量上限各自锁死，谁也别占谁的便宜。

用场景里的竞争看一遍就清楚了：A1 已经占了 user pool 一个额度，B1 先到，拿到第二个额度进 Runner，这时第三位用户 C1 来了，user pool 已满，C1 排到队首也要在门口等着，直到 B1 结束交还额度才能进去。顺序的事交给 Lane，容量的事交给额度，两条线分开，调度才理得清。

**图 P02-A｜Lane 与独立并发池怎样共同决定执行顺序**

![](images/P02/img1.jpg)

图里最重要的两条线：横向的 Lane 决定顺序，纵向的并发池决定容量。两条 Lane 可以并行，也可能因为挤同一个 user pool 而等着额度。J1 走 system pool，不占用户额度，所以在 B1、C1 挤 user pool 的时候，J1 反而能直接开始。

## A2 想插队，有三种插法

小林补的那句"只改 Python 文件"想插进正在跑的 A1，有三种插法，差别在把这句话放在哪。

一种是排在 A1 后面，等它跑完再作为一条新任务单独执行。缺点也明显，这句话可能等很久，A1 跑完都忘了这茬，但好处是干净，A1 改完的东西不会被中途打扰，普通消息、定时任务都走这条路，它是默认策略，代码里叫 **APPEND**，什么时候都安全。

还有一种聪明些，塞进 A1 正在进行的思考。A1 的 Agent 每走完一步会回头看一眼，这时候把补充递进去，"只改 Python 的"当场生效，代码里叫 **INJECT**。不过它讲究时机，A1 恰好在这一步之前结束的话，这句话就白递了，得退回来排队改走 APPEND；一旦被读走，这句话就和 A1 共用结果，之后取消它自己的句柄也影响不到 A1。INJECT 适合"补充、修正、加条件"这类要和当前任务合流的消息，不适合打断型的，它合流之后，这条补充就没有独立的命运了。

最激进的直接把 A1 停了，让这句话先跑，代码里叫 **INTERRUPT**，代价是 A1 二十秒的活儿全白干，不到万不得已不用，比如用户明确说"停下，先做这个"。Lane 空闲时没有可中断的对象，INJECT 和 INTERRUPT 都会按普通排队处理。

三种都是合理策略，保守、协作，还是强势，看你想要什么。把三种命运画在一张图里，同一个 A2，三条轨道：

**图 P02-C｜A2 的三次尝试：一个请求，三种命运**

![](images/P02/wb1.jpg)</whiteboard>

## 定时任务不能抢用户的活

J1 是定时任务，来源是 CRON。它即使带着 INJECT 或 INTERRUPT 来，也会被 Scheduler 改成 APPEND。

为什么？系统任务不能借忙时策略抢占用户正在进行的 Turn。用户优先是产品原则，它不写在某一个函数里，而是写在这种降级规则里，定时任务到点了，老老实实排队，等用户的任务跑完，系统再插嘴，世界就乱套了。

这和并发池隔离是一个道理的两面。额度那边，system pool 不占用户的位置；策略这边，系统请求一律 APPEND，不让它插队。两层都挡住，用户的任务才有不被干扰的底气。

## 谁在等结果

调度器把请求接进来，谁在等结果？A1 的调用方是 gateway 的入站循环，J1 的调用方是 cron 调度，它们 `submit()` 后拿到一个 `TurnHandle`，通常这样等：

```python
handle = scheduler.submit(request)
outcome = await handle.result()
```

Handle 内部持有一个 Future，可以理解成这条 Turn 将来会给出的结果，Lane worker 完成 Future 时，所有等待者都会醒来。

等待分三种情况，结局不同。

等待者自己先走了（被取消）：`result()` 用 `asyncio.shield()` 保护了底层任务，外层等待取消，底层 Turn 继续跑。A1 已经跑了二十秒，不能因为没人等就把任务杀掉，那是浪费已经投入的时间，等待和任务本来就该解耦，谁在等不影响任务跑不跑。

排队中取消：调用 `handle.cancel()`，Lane 把请求从队列或注入邮箱移除，结果直接是 None，Runner 从未启动，东西还没开始，撤掉就行。

运行中取消：Lane 只取消 `_run_task`，worker 在 finally 里完成宿主 Future，自然返回、异常、取消都从同一个出口走。

这个单一出口是收尾的关键，如果取消方法、Runner、shutdown 都能直接完成同一个 Future，自然结束和取消撞在一起时就可能出现双重完成，或者留下一个永远等不到的 Handle。

终态有三种：Completed、Failed、Cancelled。代码里 `TurnHandle.result()` 返回 `TurnOutcome | None`，失败和取消再由 `TurnFailed(cancelled=...)` 区分。

**图 P02-B｜三种策略的去向与终态收口**

![](images/P02/img2.jpg)

这张图的上半部分是三种策略的去向，和前面的图是同一件事、两种画法；下半部分是终态收口，Completed、Failed、Cancelled 都从同一个 worker 出口出来。

## 退出服务，谁先走

小林退出服务。排队中的请求和运行中的请求，命运不一样，`shutdown(grace)` 分四步处理：

1. 停止接收：设排空标记，新的 `submit()` 立即失败；
2. 清理没开始的：排队项和没读的注入，直接以 None 结束；
3. 等运行中的：给 `grace` 时间让它们自然完成；
4. 超时取消：还没跑完的取消，等 Future 收口。

为什么给运行中的请求时间？A1 已经跑了二十秒，让它跑完比砍掉它更符合直觉，grace 就是"值得等的任务，等它一下"，等不到才动手砍。

停止接收和清理没开始的请求之间没有异步等待点，这是为了避免运行中的 Turn 恰好结束，把注入重新排队到一个已经完成清理的 Scheduler，那会乱套，排空标记就是为了让这两步之间不留缝。

多个调用方同时执行 shutdown，会共享同一条关闭任务，调用方在等待期间被取消，内部的安全收尾仍会完成，取消再向外传播。

## Turn 结束，不等于消息送达

`handle.result()` 返回，只是执行终态，正文可能还在 Delivery 队列里，还没发给用户。Scheduler 的事件出口同时接收生命周期事件和 Runner 输出，只有 Runner 输出会交给 DeliveryHub，生命周期事件不会被当作聊天消息发出去。要确认用户真的收到了，得等 `DeliveryHub.wait_idle(channel)`，看渠道发送队列有没有排空。渠道最终发送失败会记录独立的投递结果，不会改写已经形成的 Turn 终态，这条链路在 P08 展开。

## 代码印证：先看整体，再挑关键处

前面讲的是方案。看真实代码，先对整体，再挑关键处。

### 整体：一次提交的时序

对应 `pico/spine/scheduler.py`：

```text
1. Host 创建 TurnRequest，调用 scheduler.submit(req)   # 立即返回，不阻塞
2. Scheduler 按 conversation 找到（或创建）Lane
3. Lane 按 busy policy 放请求：队尾 / 注入邮箱 / 队首
4. worker 从队首取一条，开始这一轮 _run_turn
5. 等 origin 对应的并发池额度（user / system）
6. 取得额度后发出 TurnStarted
7. TurnRunner 执行 Agent Loop，发出正文、工具事件
8. Spine 发出 TurnEnded / TurnFailed
9. worker 完成 TurnHandle 的 Future
10. 回到第 4 步，处理下一条
```

注意时序里的先后：TurnStarted 只在取得额度之后发出，请求已经离开队列、还在等额度的时候，不算开始。Runner 只能发正文、工具这类内容事件，TurnStarted、TurnEnded、TurnFailed 由 Spine worker 统一管，Runner 发这类生命周期事件会直接 TypeError，这个分工就是前面"生命周期一个出口"的落地。

### 局部一：Lane.submit 的三分支

```text
Lane.submit(req, policy)

if policy == INTERRUPT 且正在运行中:
    取消当前 _run_task
    把 req 放到 _pending 队首
elif policy == INJECT:
    放进 _inject_mailbox          # Agent Loop 下次 drain() 读走
else:   # APPEND
    放进 _pending 队尾
```

### 局部二：\_run_turn 的额度和生命周期

```text
Lane._run_turn(req)

async with origin_pools.acquire(req.origin):   # user / system 额度
    发出 TurnStarted
    outcome = await runner.run_turn(req)        # Agent Loop 在里面跑
    发出 TurnEnded / TurnFailed
# 退出 with 即归还额度
```

### 局部三：\_run_worker 的单点完成

```text
Lane._run_worker()

while 队列非空:
    req = 取队首
    fut = 这条请求的 Future
    try:
        outcome = await _run_turn(req)
    finally:
        fut.set_result(outcome)    # 唯一完成 Future 的地方
    # 自然结束、异常、取消都从这里收口
```

### 局部四：shutdown 四阶段

```text
Scheduler.shutdown(grace)

1. _draining = True                        # 新 submit 立即失败
2. 清理未开始：排队项、未读注入 → Future 以 None 结束
3. await 等待运行中任务，最多 grace 时间    # 宽限期内自然完成
4. 取消超时任务，等 Future 收口
```

### 文件地图

第一次读代码只看这几个入口：

| 顺序 | 文件与符号 | 看什么 |
|-|-|-|
| 1 | `pico/spine/turn.py::TurnRequest` | origin、conversation、busy 三个字段 |
| 2 | `pico/spine/scheduler.py::Scheduler.submit` | conversation 怎样映射到 Lane |
| 3 | `pico/spine/scheduler.py::Lane.submit` | busy policy 怎样改变请求位置 |
| 4 | `pico/spine/scheduler.py::Lane._run_worker` | 串行执行和 Future 单点完成 |
| 5 | `pico/spine/scheduler.py::Lane._run_turn` | 并发池、生命周期和 Runner |
| 6 | `pico/spine/scheduler.py::Scheduler.shutdown` | 四阶段关闭 |
| 7 | `pico/spine/delivery.py::DeliveryHub` | 执行终态与投递终态的边界 |

### 用测试验证

| 想验证什么 | 先读哪个测试 |
|-|-|
| 同会话有序、跨会话并行与生命周期 | `tests/test_spine_scheduler.py` |
| Lane 取消、注入和 worker 竞争 | `tests/test_spine_scheduler_lane.py` |
| user / system 并发池隔离 | `tests/test_spine_scheduler_pools.py` |
| Delivery 队列与发送终态 | `tests/test_spine_delivery.py` |

### 20 分钟练习

目标：为四条请求标出各自的 Lane、pool 和最终结果，验证本章的方案。

1. 打开 `pico/spine/turn.py`，写下 `origin`、`conversation`、`busy` 三个字段；
2. 在 `Scheduler.submit()` 找到 conversation 到 Lane 的映射；
3. 在 `Lane.submit()` 标出 APPEND、INJECT、INTERRUPT 三条分支；
4. 在 `_run_turn()` 找到额度获取和 TurnStarted 的先后；
5. 在 `_run_worker()` 找到 Future 的唯一完成点；
6. 在 `shutdown()` 找到四个阶段；
7. 回到图 P02-D，为每条请求标出 Lane 和 pool。

建议边读边填：

```text
请求 | conversation | origin | busy | 进入哪里 | 结果由谁完成
```

完成后回答：

- A1 正在运行时，A2 选 APPEND 和 INJECT 有什么差异？（排队等 vs 并入当前任务）
- user pool 满时，为什么 J1 仍可能开始？（system pool 独立，互不借用）
- 等待 `handle.result()` 的外层任务被取消，底层 Turn 会怎样？（shield 保护，继续跑）
- Handle 已完成，怎样确认用户收到了消息？（等 Delivery 终态，见 P08）

## 用时间线验证

设定：user pool 容量为 2，system pool 容量为 1。除 A1、A2、B1、J1 外，还有第三位用户 C1，比 B1 晚到。整个过程：

**图 P02-D｜四条请求的时间线**

![](images/P02/wb2.jpg)</whiteboard>

读这条时间线，注意三个时刻：C1 排到队首却不进 Runner，因为 user pool 满了，这是容量约束；J1 在 user pool 挤满时照常开始，因为走 system pool；t=1.0 B1 结束，C1 才拿到额度。A1 如果在 t=0.8 前已经结束，A2 会进入 Lane A 尾部，随后作为独立 Turn 执行。

## 划重点

最后压一下这章的内容，方便回看。判断"谁先谁后"，先分清是顺序问题还是容量问题，顺序靠 Lane，容量靠额度；忙时策略本质是产品决策，同一个请求是排队、合流还是打断，取决于你想要保守、协作还是强势，系统任务一律排队；收尾记住结果只有一个出口，Future 必须单点完成，多个地方都能收就会出双重完成或者永久等待。

## 数据怎么说

调度收益有受控实验支撑，前台排队时间、共享池与独立池的对比、请求归宿的可靠性，数字和口径都在 P11，这里不展开。

## 接下来怎么读

- [P03｜Agent Loop](https://icnoljnkix43.feishu.cn/wiki/Wy0GwYki7iy2X6kDM1ncyrgInVd)：Runner 取得请求后，怎样反复调用模型和工具；
- [P08｜Channels 与 Delivery](https://icnoljnkix43.feishu.cn/wiki/LM0vwlNRqi08c0k9ilgcKsQSnte)：执行完成后，回复怎样进入渠道；
- [P10｜Tracing](https://icnoljnkix43.feishu.cn/wiki/OS4WwBltmi3v5gkfmQ8cPVmOnec)：Turn 与 Delivery 的终态怎样进同一条 Trace；
- [P11｜PicoBench](https://icnoljnkix43.feishu.cn/wiki/XTOEwv9vhig1IikThC8cOJXEnrg)：调度实验的 manifest、raw record 和 Gate 怎样重建。