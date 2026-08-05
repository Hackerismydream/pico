# 06 Session：账本、栅栏与跨进程证明

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。
> 本章中的 EverOS 与 V-O0 跨进程段落是已移除实现的历史证据；Session 栅栏仍适用，当前 Memory 边界见 [Memory 架构](../memory-plugin-architecture.md)。

读完这一篇，你应该能回答：

- 会话为什么用 JSONL 追加而不是 JSON 整写，崩在半路会发生什么
- 追加和重写的切换条件为什么是「比前缀」而不是「比条数」
- 两个进程写同一个会话怎么不打架，「删除后复活」这类幽灵 bug 靠什么挡住
- fork、export、undo、delete 各自的精确语义和边界
- 「resume 恢复的到底是什么」这道题的新答案
- 跨进程连续性是怎么被证明的（三进程探针和一个叫 Cobalt Lantern 的暗号）

## 一、问题：账本错了，全系统跟着错

把场景钉死再谈机制。你在 TUI 里跟 agent 聊了四十轮，第十二轮它读了一个大文件，第二十八轮你纠正过它一次。这时候进程被 `kill -9`；或者你手快，在另一个终端也打开了同一个会话；或者你昨天删掉的那个会话，今天又出现在列表里。重开之后你的期待很朴素：四十轮原样都在，纠正过的那轮仍然是纠正过的样子，删掉的就是删掉了。

承担这份期待的是 Session。它是整个系统的账本：上下文引擎按它装配 prompt（第 03 章），记忆从它蒸馏（第 05 章），复盘和评测读它还原过程。账本错一条，下游全部跟着错，而且错得悄无声息，prompt 里少一轮，模型这一轮的回答就变了，可没有任何一处会抛异常。

朴素做法的三种死法，每种在这个仓库里都有对应的测试名字当墓志铭：

1. **内存 dict 加定期 dump 整个 JSON。** 崩溃丢掉自上次 dump 以来的一切。更糟的是整写崩在半路，文件前半是新内容、后半是上一版的残尾，JSON 解析器一读就报错，四十轮一起作废。
2. **两个进程写同一个会话，互相覆盖。** gateway 和 CLI 同时活着的系统里这不是假设，是日常：进程 A 读到 40 条，进程 B 也读到 40 条，各自追加两条写回去，先落地的那两条被后落地的整体抹掉。
3. **没有身份栅栏。** 会话被删了，一个还攥着旧句柄的进程迟到写入一笔，被删的会话凭空复活；或者同一个 key 删除后重建，旧进程把上一代的数据写进新会话，两代内容混成一份谁也看不出问题的历史。

第三类最阴险，它不丢数据，它造数据。先记住三个真实存在的测试名：`test_cross_process_late_save_cannot_recreate_deleted_session`、`test_stale_session_cannot_append_after_deleted_key_is_reused`、`test_lazy_session_cannot_append_after_key_is_created_deleted_and_reused`。三个测试防的是同一族幽灵：一个手里攥着过期身份的写者。

## 二、三种存法的账

会话持久化的选型空间不大，三族做法各有各的账，先把账算清楚再看 Pico 选了什么。

**进程内存加退出时落盘。** 写起来最省事，代价是崩溃窗口等于整个会话的生命周期。agent 恰恰是长时间运行、频繁拉起子进程、随时可能被信号或 OOM 打断的那类程序，这个窗口开得太大。

**单文件 JSON 快照，每轮整写。** 崩溃窗口缩到一轮，但每轮都要把全量历史重新序列化并覆盖原文件。写到一半断电，旧内容已经被截断、新内容还没写完，整个文件报废；历史越长，这个窗口越宽。

**关系数据库或 KV。** 事务和并发交给引擎兜底，代价是把一个能 `cat`、能 `grep`、能 diff 的文本文件换成需要专用工具才能打开的黑盒，本地 agent 的调试和手工修复全部变难，还多一个必须随发行版分发的运行时依赖。

Pico 走的是第四条：每会话一个只追加的 JSONL 文件，只有改写历史时才退化成原子整写。追加的三个性质刚好对上前面三种死法：写入代价只跟新增量有关，崩溃最多损坏最后一行，字节序天然就是消息序。`Session` 类的 docstring 把第四条理由也写上了，`Messages are append-only for LLM cache efficiency`，历史前缀稳定，provider 侧的前缀缓存才有得命中（第 04 章的缓存断点就架在这个前提上）。

可迁移的判断：当写入模式是「只在尾部增长」时，追加文件通常比整写快照划算；只有真的需要跨记录事务和二级索引，才值得把数据库那份复杂度买回来。

## 三、数据模型：一个 key，两类行，一个咽喉

会话身份是 `channel:chat_id`。CONTEXT.md 的词条把语义定死了：channel 是维度（key 前缀、存储子目录、元数据字段），不是用户可见身份的一部分；身份活在 chat_id 槽里。用户面前露出的「session id」就是剥掉 channel 前缀的那半截，回到代码里再拼回去。

chat_id 的铸造只有 9 行，`pico/session/manager.py`：

```python
def new_chat_id(now: datetime | None = None) -> str:
    """Mint an opaque, sortable per-session chat_id: ``YYYYMMDD_HHMMSS_xxxxxx``.

    Sortable by value (timestamp prefix) and collision-safe (uuid suffix);
    channel-agnostic. Becomes the session key's chat_id segment and the JSONL
    filename stem.
    """
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:6]}"
```

时间戳前缀让文件名天然按时间排序（`ls` 出来就是时间序，不需要额外索引），6 位 uuid 后缀防同秒撞车，同一个格式同时充当 key 片段和文件名 stem。磁盘布局是 `<workspace>/sessions/<channel>/<chat_id>.jsonl`。

### 文件长什么样

抽象说三句不如看一眼实物。下面这份是现场跑出来的：新建一个 `cli` 会话、设标题、存两条消息、save，再追加一条消息、再 save（口径：在临时 workspace 上直接调 `SessionManager`，工作树 `76d3761`）。

```jsonl
{"_type": "metadata", "key": "cli:20260726_101500_a1b2c3", "created_at": "2026-07-27T01:20:44.690642", "updated_at": "2026-07-27T01:20:44.690651", "metadata": {"source": null, "channel": "cli", "chat_id": "20260726_101500_a1b2c3", "title": "demo", "parent_session_id": null}, "last_consolidated": 0, "pending_clarification": null}
{"role": "user", "content": "hello", "timestamp": "2026-07-27T01:20:44.690646"}
{"role": "assistant", "content": "hi", "timestamp": "2026-07-27T01:20:44.690650"}
{"_type": "metadata", "key": "cli:20260726_101500_a1b2c3", "created_at": "2026-07-27T01:20:44.690642", "updated_at": "2026-07-27T01:20:44.691885", "metadata": {"source": null, "channel": "cli", "chat_id": "20260726_101500_a1b2c3", "title": "demo", "parent_session_id": null}, "last_consolidated": 0, "pending_clarification": null}
{"role": "user", "content": "again", "timestamp": "2026-07-27T01:20:44.691882"}
```

四件事直接从这五行读出来：

- **只有两类行。** `_type == "metadata"` 的元数据行，和其余任意 dict 的消息行。解析时按 `_type` 分流，消息行不做 schema 校验（工具调用、多模态块、reasoning 块形状各异，账本不替它们定型）。
- **第二次 save 又追加了一条 metadata 行。** 元数据是可变的（updated_at、标题、水位、待澄清状态），文件是只追加的，调和办法就是每次 save 都追一条新的，读取时以最后一条为准。原地更新元数据会破坏追加语义，也就守不住「旧字节永不被改」这条。`test_find_most_recent_reflects_latest_append` 钉的就是这条：最近更新时间必须读最后一条 metadata，不是第一行。
- **五个保留槽。** `save()` 每次都把 `source / channel / chat_id / title / parent_session_id` 兜底填进 metadata（已有值优先），所以任何一个会话文件都能自证它属于哪个 channel、哪个 chat_id、有没有父会话。`test_save_reserves_metadata_keys` 钉住这五个键。
- **每条消息只有一个时间字段。** 没有 turn_id，没有 received_at。

### 一个咽喉

写入只有一个入口，`Session.record()`：盖时间戳、追加进 messages、刷新 updated_at。`add_message`、agent loop 的 `_save_turn`、澄清问答的回写，全部从这里过。docstring 讲了为什么不多盖章：

> Per-message ordering and turn grouping derive from append order and the `role` boundary, so no separate received_at / turn_id stamp is kept.

轮次分组由追加顺序和 role 边界推导，少一个字段就少一处需要维护一致性的地方。`test_record_stamps_timestamp_only` 反向断言 `received_at` 和 `turn_id` 都不许出现，`test_load_preserves_on_disk_message_order` 更进一步：文件里就算写了乱序的 `received_at`，加载出来也按文件顺序排，字节序是唯一的顺序真相。

### 身份自检

读取一个会话时要做三重身份核对，任何一重不过就是 `StorageCorruptionError`，不猜、不改名、不静默换一个会话给你：

1. metadata 行里的 `key` 必须等于请求的 key（`_validate_metadata_identity`）；
2. 文件里一条 metadata 都没有时，退回用路径推身份（父目录名是 channel，stem 是 chat_id），此时请求的 key 必须等于这个规范 key（`_validate_fallback_identity`）；
3. 同一个文件里多条 metadata 行的 key 必须互相一致（`_scan_file` 里的 `identity` 变量）。

`test_metadata_key_collision_fails_closed`、`test_corrupt_identity_line_cannot_fall_back_to_canonical_alias` 是这三条的反例测试。可迁移的一条：任何「文件名即身份」的存储，都要让文件内容自己也带一份身份，并在读取时对账，否则一次改名、一次拷贝就能把两个实体悄悄接到一起。

## 四、原子性：追加、栅栏、修复

### 两条写路径

常规存盘走追加：只写「上次持久化之后的新消息」，外加一条新的 metadata 行。判定是否还能追加的代码在 `SessionManager.save`：

```python
persisted_messages = (
    session._persisted_snapshot.get("messages") if session._persisted_snapshot is not None else None
)
append_only = (
    persisted_messages is not None
    and len(session.messages) >= len(persisted_messages)
    and session.messages[: len(persisted_messages)] == persisted_messages
)
rewrite = force_rewrite or session._requires_rewrite or (session._persisted and not append_only)
```

判定的核心是最后那个前缀比较：内存里的消息列表，前 N 条要跟磁盘上已持久化的 N 条逐条相等，才允许只追加尾巴。前缀不再相等（undo、clear 改写了历史，或者某条消息被原地改过），就切换到重写路径：写临时文件、fsync、`os.replace` 原子换入，同时代际号加一。

为什么必须比前缀而不是比条数？因为「历史被改过」和「历史变短了」不是一回事。撤销两轮再补两轮，条数一模一样，内容全变了；把某条消息的 content 原地改一个字，条数根本没动。这两种情况下按条数判定都会选择追加，结果是新内容追在旧内容后面，磁盘上留下一份内存里从未存在过的历史。这不是假设，是这个仓库真实发生过的形态，第九节有当时的代码。现在有 `test_flush_persists_equal_length_message_mutation` 专门钉等长原地修改这一路。

### 追加时的半行修复

追加本身的崩溃安全在 `pico/utils/atomic_io.py`：

```python
with open(path, "a+b") as f:
    payload = "".join(line + "\n" for line in lines).encode("utf-8")
    # A crashed writer can leave a partial line without a trailing
    # newline; start on a fresh line so records never merge.
    if f.tell() > 0:
        f.seek(-1, os.SEEK_END)
        if f.read(1) != b"\n":
            payload = b"\n" + payload
    f.write(payload)
    f.flush()
    os.fsync(f.fileno())
```

上一个写者崩在半行（文件不以 `\n` 结尾），下一个写者先补一个换行再写自己的内容，两条记录永不粘连成一条谁也解析不了的怪行。写完 flush 再 fsync，落到磁盘才返回。`test_locked_append_repairs_missing_trailing_newline` 钉这个细节。

### 三层栅栏

一个目录下的会话文件旁边有两个隐藏侧车目录，跑一次 save 就能看见全貌：

```text
sessions/cli/20260726_101500_a1b2c3.jsonl
sessions/cli/.lock/20260726_101500_a1b2c3.jsonl.lock
sessions/cli/.generation/20260726_101500_a1b2c3.jsonl.epoch
sessions/cli/.generation/20260726_101500_a1b2c3.jsonl.known
```

**互斥靠 `.lock/` 里的锁文件。** 用 portalocker（POSIX `fcntl` 加 Windows `LockFileEx`），进程死了操作系统自动释放，不需要任何清理陈锁的逻辑。锁文件藏在隐藏子目录里，`ls` 会话目录只看得见 transcript，`test_no_lock_sidecar_beside_session_jsonl` 连这个都钉了。

**防「删除后复活」靠 `.generation/` 里的代际号。** `.epoch` 存一个整数，`.known` 是一个「这个路径有过持久身份」的标记。删除和重写会推进代际号，追加不会。跑一遍就看得很清楚（口径：临时 workspace 上依次 save、追加 save、undo 后 `commit_history_rewrite`、delete，每步读一次 `.epoch`，工作树 `76d3761`）：

```text
第一次 save（新建）      epoch = 0
追加一条再 save          epoch = 0
undo 后提交（整写）      epoch = 1
delete                   epoch = 2，主文件消失
```

任何写入都带上自己以为的代际号，对不上就被拒：

```python
if expected_epoch is not None and current != expected_epoch:
    raise FileNotFoundError(f"file was deleted or replaced before {operation}: {path}")
```

一个在 epoch=0 时加载的旧进程，等它迟到写入的时候磁盘上已经是 epoch=2，`FileNotFoundError` 当场拦下，被删的会话不会被它复活。第一节那三个幽灵测试跑的就是这条路。`.known` 标记负责另一半：`.epoch` 读不到但 `.known` 还在，说明代际元数据自己丢了或坏了，`read_epoch` 抛 `StorageCorruptionError`，而不是当成「一个全新的、从没存在过的路径」放行一个 epoch=0 的写者（`test_missing_epoch_after_generation_change_rejects_stale_epoch_zero_writer`）。区分「从没有过」和「有过但记录没了」，是这类栅栏能不能守住的关键，只存一个计数器是不够的。

**防「元数据被并发改了还往上追加」靠内容栅栏。** save 在持锁状态下重读磁盘，比对三项：metadata、`last_consolidated` 水位、`pending_clarification`。任何一项跟自己的快照不一致，`_validate_append_base` 抛 `session metadata changed before append` 放弃这次追加。整写路径的 `_validate_rewrite_base` 更严，四项（含全部消息）必须完全相等才允许换入，所以「A 撤销的同时 B 追加了两轮」这种情况下，A 的整写会被拒，B 的两轮不会被 A 的旧视图抹掉（`test_history_rewrite_rejects_messages_appended_after_snapshot`）。

三层的分工可以这样记：锁管「同一时刻只有一个人写」，代际号管「你写的是不是这一代」，内容栅栏管「这一代在你读完之后有没有被动过」。

### 坏文件怎么处置

读取时对损坏分级，界线划在「是不是最后一行、有没有结尾换行」：

- **文件末尾的半行**（崩溃写者的遗迹）跳过，同时给会话打上 `_requires_rewrite`，下一次 save 强制走整写路径产出一份干净文件。`test_save_after_partial_trailing_line_rewrites_clean_transcript` 断言修复后文件里再也搜不到那半行。
- **末尾截断在多字节字符中间**（半个 UTF-8 码点）先降级成替换符再按半行处理，不让一个 UnicodeDecodeError 把整个会话变成不可读。
- **中间位置的坏 JSON 或非法 UTF-8** 一律 `StorageCorruptionError`，不猜不修（`test_invalid_utf8_before_eof_fails_closed`）。中间坏了意味着损坏原因不是「写到一半停电」，硬猜只会把错误往下游传。

还有一个容易漏掉的对称条款：**看见半行的陈旧写者不许直接往上追加**。`_validate_append_base` 发现 `partial_tail_found` 就抛 `session has a partial trailing record before append`，逼这个写者重新加载。理由是它手里那份内存视图是在损坏发生之前读的，让它追加等于把损坏永久夹在历史中间。`test_stale_append_rejects_recoverable_partial_trailing_line` 还额外断言被拒之后文件字节一个都没变，随后一个新加载的 manager 能正常修复。修复权只交给看过损坏现场的读者。

**只读目录的降级读。** 权限受限的环境（只读挂载、`EROFS`）拿不到锁，`_load_state` 降级成无锁快照读：读之前读之后各取一次「代际号 + known 标记 + 文件是否存在」，三元组一致才接受这次快照，最多重试 3 次，三次都撞上并发变更就 `StorageCorruptionError`。

**一条没做的事，如实交代。** `atomic_replace` 对临时文件做了 fsync，但 `os.replace` 之后没有对父目录做 fsync。也就是说在某些文件系统上，断电可能让重命名本身丢失（回到旧文件），换入的原子性在崩溃语义下是「新旧二选一」而不是「一定是新的」。这对会话账本可以接受（旧的那份仍然是一份自洽的历史），但如果你把这套原语搬去存对账数据，目录 fsync 得补上。

## 五、生命周期：六个动词的精确语义

**create 有懒急两态。** 裸 `sessions create` 只铸 id 不落盘，文件在首次使用时才物化；带 `--title` 则立即持久化。`pico/cli/session_commands.py` 的模块 docstring 解释了这个分叉：

> This diverges from the TUI's lazy semantics because the CLI process dies immediately after the command returns, leaving no opportunity for a later lazy flush.

CLI 进程命令返回就死，没有「稍后懒刷盘」的机会，TUI 才有。同一段 docstring 还诚实标了懒态的副作用：一个铸了却从没用过的 id，`resume` 是找不到它的，因为磁盘上根本没有文件，所以 `create` 的输出里带一句提醒。

**fork 是全量深拷贝的 fork-at-head。** 子会话拿新 chat_id（同 channel）、深拷贝父的全部消息、`parent_session_id` 记血缘、继承 `last_consolidated`（fork 点的活动窗口和父一致）、重置 `pending_clarification`（交互等待状态不是历史）、立即持久化。三个前置条件会让它返回 None：源不存在、源 flush 失败、源没有任何消息。标题规则也是定死的：显式给了就用，没给而父有标题就是 `<父标题> (fork)`，父没标题就不给标题。fork 之后父子各写各的，互不可见，这条有三进程探针证明（第七节）。

**export 是带自校验的信封。** schema 常量 `pico.session.export.v1`，payload 装 9 个字段：`key`、`created_at`、`updated_at`、`metadata`、`last_consolidated`、`pending_clarification`、`messages`、`message_count`、`transcript_markdown`（最后一个是渲染好的 Markdown 视图，方便人读）。摘要的算法写死在 `_payload_digest`：

```python
canonical = json.dumps(
    payload,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
return hashlib.sha256(canonical).hexdigest()
```

`sort_keys` 加紧凑分隔符构成 canonical form，同样的内容永远算出同样的摘要。`verify_export` 校验四件事：schema 常量对不对、9 个字段齐不齐、`message_count` 跟 `len(messages)` 等不等、摘要重算对不对。改一个字节就报废，`test_portable_export_verification_rejects_modified_body` 钉篡改检测。CONTEXT.md 的词条特意提醒别把它叫「transcript export」，Markdown 只是其中一个字段，不是可携带记录本身。导出物自包含：源会话删掉之后它依然可验证。

**undo 以 user 消息为界撤整块。** 一个 turn 从一条 `role == "user"` 消息起，到下一条 user 消息之前结束（中间的 assistant、tool 消息都归它）。`undo_last_turn(n)` 撤掉最后 n 块并返回删掉的消息条数，连带清空 `pending_clarification`。两条边界：可撤范围只有 `messages[last_consolidated:]`，已经蒸馏进记忆文件的内容永不跨过；n 大于现有块数时钳到该尾部的第一条 user 消息，不会撤穿。落盘是调用方的事（`SessionManager.save` 或 `commit_history_rewrite`），`undo_last_turn` 自己只动内存。

**delete 是安全 no-op 加显式边界。** 删除未知 key 不报错，返回 False；删除已知 key 推进代际号，让一切迟到写入失效；`allow_cached_missing` 让一个从未落盘的懒会话也能被逻辑删除（栅栏照样推进，防的是旧引用在空位上重建）。边界必须原样背下来，`docs/architecture/state-and-intelligence.md` 的原话：

> Deleting a Session does not imply deletion of Curator archives, EverOS semantic Memory, or traces. Those domains have separate ownership.

**clear 与 undo 的提交有个特殊栅栏。** `commit_history_rewrite` 正常情况下就是 `save(force_rewrite=True)`，但懒会话（从未落盘）被撤空后没有文件可重写，这时走 `locked_delete(..., fence_missing=True, increment_epoch=True)`，把「这个路径此刻不存在」这个事实本身也钉进代际号。不这么做的话，一个旧写者会看见「文件不在、代际号 0」，以为自己面对的是一个全新路径，把撤掉的历史重建出来（`test_lazy_history_rewrite_fences_stale_manager_without_materializing_file`）。

## 六、和 AgentLoop 的缝：落盘前的过滤与顺序纪律

每轮结束，`_save_turn` 只落「本轮新增」的切片（从 `turn_start_idx` 起），而且不是原样照抄。六道过滤，每道背后都有一次教训（`pico/agent/loop/main.py`）：

1. **subagent 回注 turn 的首条 user 消息不存。** 那是内部脚手架（把子 agent 的结果宣告回主会话），不是用户说的话，存进去下一轮 prompt 里就多一句用户从没说过的话。
2. **恢复机制注入的合成 nudge 不存。** 带 `_recovery_synthetic` 标记的消息直接跳过，注释把话说死：`never persist scaffolding`。恢复机制为了把卡住的模型推一把而合成的消息，是运行时的手段，不是对话的一部分。
3. **空 assistant 消息不存。** 条件是 role 为 assistant、content 为空、且没有 tool_calls，注释原话 `they poison session context`。
4. **工具结果截断。** `_TOOL_RESULT_MAX_CHARS = 16_000`（`pico/agent/loop/main.py:233`），超长部分截掉并追加 `\n... (truncated)` 标记，让后续读到的人知道这里被截过。
5. **user 消息剥掉 runtime-context 前缀。** 上下文引擎每轮往 user 消息前面拼一段运行时上下文（时间、工作区之类），账本只留用户原话；剥完如果什么都不剩，这条消息整个丢弃。多模态列表同理逐块过滤，其中 `data:image/` 开头的 base64 图片块换成 `[image]` 占位。
6. **最后过一遍 `sanitize_persisted_payload`。** 这一步递归扫描整个消息 dict（含嵌套的 list、tuple、set），用正则把任何字符串里内联的 `data:image/...;base64,...` 换成 `[image data omitted]`。第 5 道管的是结构化的多模态块，这一道管的是藏在自由文本里的 data URI，两道合起来才能保证账本不装二进制。

顺序纪律是这一节的承重条款：先 `_save_turn` 加 `sessions.save`，后记忆 store。`_dispatch_backend_store` 的 docstring 原话：

> Backend failures propagate after the append-only Session save, so the Turn cannot be reported as successful when indexing failed.

账本永远先于索引。这样安排之后，失败的形态只有一种（记忆没索引上，但对话记录还在，下次可以重放补索引），而反过来会出现「记忆里有、账本里没有」这种没法自愈的状态。

### TUI 那侧的三条纪律

`pico/tui_rpc/methods/session.py` 注册了 11 个 RPC：create / close / resume / list / delete / most_recent / title / clear / undo / branch / export。三条纪律值得记：

**变更类方法先查 lane 有没有在跑的 turn。** close、delete、clear、undo 都在最前面调 `turn_module.is_turn_active(session_key)`，忙则抛 `TurnInProgressError`。理由 `session_clear` 的 docstring 写了：`mutating history under a running writer races`。

**delete 走确认往返，而且确认前后都要复查。** 处理器在弹确认框之前先抓两个快照，`storage_epoch` 和 `file_existed`，等用户点完确认再把这两个值当 `expected_epoch` / `expected_exists` 传给 `manager.delete`。确认框开着的那几秒里如果同一个 key 被别人删掉又重建，代际号已经变了，`locked_delete` 的 epoch 检查失败，`manager.delete` 吞掉这个 `OSError` 返回 False，处理器给出 `{"deleted": None}`，新一代内容原封不动。三个测试钉三种窗口期竞态：`test_session_delete_rechecks_active_turn_after_confirmation`（确认期间开了新 turn，抛 `TurnInProgressError`）、`test_session_delete_does_not_remove_recreated_generation_during_confirmation`（确认期间同 key 被删后重建）、`test_session_delete_does_not_remove_new_lazy_file_created_during_confirmation`（确认期间懒会话被别的进程落了盘），后两个都断言磁盘上留下的是新一代的内容。

**落盘失败要整体回滚内存。** `session.clear` 在调 `commit_history_rewrite` 之前备份 5 项（messages、last_consolidated、updated_at、metadata、pending_clarification），失败就整体还原并返回 `cleared: False`；`session.undo` 备份 4 项（不含 `last_consolidated`，因为 undo 本来就不许跨水位，这个值不会变）。内存和磁盘不允许分家，否则用户看见的是「已清空」，重启之后历史又回来了。

顺带一个 API 细节：`session.resume` 返回的是 `session.messages` 原样，不是 `get_history()`。docstring 解释了区别，`get_history` 会切窗口、还会丢掉开头的非 user 消息（避免孤儿 tool_result），那是喂给模型的视图；给前端重放历史必须是 N 存 N 出。同一份数据，喂模型和给人看是两种视图，这个区分值得带走。

## 七、跨进程证明：三个进程和一个暗号

「连续性」这个词很容易吹成玄学，这个仓库把它拆成了两个可执行的证明。

### 确定性层：三进程接力加一次真 CLI

`tests/integration/test_session_continuity_e2e.py` 用 `subprocess` 起三个独立的 Python 进程，按顺序跑同一个 workspace，探针脚本是 `tests/integration/_session_continuity_probe.py`：

- **进程一（seed）**：建父会话 `cli:continuity-parent`，写两条消息（`shared question` / `shared answer`），fork 出子会话，再写一份 portable export 并当场 `verify_export`。
- **进程二（diverge）**：重新打开父子两个会话，先断言 `_contents(parent) == _contents(child)`（fork 保留了历史），然后父加一条 `parent only`、子加一条 `child only`，各自 save，最后删掉父会话。
- **进程三（verify）**：验收。断言就是前六节的全部承诺：

```python
if parent is not None:
    raise RuntimeError("deleted Session resumed in a fresh process")
if child is None:
    raise RuntimeError("deleting the parent removed its child")
if "parent only" in _contents(child) or "child only" not in _contents(child):
    raise RuntimeError("post-fork writes were not isolated")
if not verify_export(export_path):
    raise RuntimeError("portable export did not survive Session deletion")
```

探针把结果打成 JSON 打到 stdout，测试主体再对第三个进程的整份输出做一次字典相等断言（子会话内容、`parent_session_id` 指回父 key、`export_verified`、`parent_not_found` 四项一个不少），并单独断言第二个进程看到的父会话内容是三条。四条承诺各对一个机制：删除生效对代际栅栏，父删子留对 fork 的独立 chat_id，写入隔离对深拷贝，导出可验证对 SHA-256 自校验。

第四个进程跑的是真 CLI，不是库调用：

```python
resume = subprocess.run(
    [sys.executable, "-m", "pico.cli.commands", "sessions", "resume", <已删除 id>],
    env={**os.environ, "PICO_HOME": str(product_home)},
    ...
)
assert resume.returncode == 1
assert "No session matching id/prefix" in resume.stdout
```

退出码和用户可见的错误文案都进了断言。库里的语义正确不等于用户拿到的行为正确，这一步补的是那段落差。

### live 层：Cobalt Lantern

记忆的跨进程连续性没法用假后端证明（假后端存什么召回什么，证明不了真实的检索链路），V-O0 的必需 live 层是这么设计的（`tests/integration/test_everos_continuity_real_llm.py` 加 `_everos_continuity_probe.py`）：

**进程 A** 在 workspace-a 的 session-a 里存一句 `my continuity codename is Cobalt Lantern`，然后等 EverOS 的处理队列彻底排空。「排空」有五个同时成立的条件，写在 `_drain_after` 里：最大 LSN 比基线大（说明这次写入确实进了队列）、pending 为 0、`last_processed_lsn == max_lsn`（处理位点追平）、可重试失败为 0、永久失败为 0。整个等待包在 240 秒超时里。

**进程 B** 换 workspace（workspace-b）、换 session（session-b）、换进程 nonce，用一个假 provider 跑一轮真实的 `run_turn`，问「我让你记的暗号是什么」。假 provider 不生成回答，它只做一件事：

```python
prompt_words = set(
    re.findall(
        r"[a-z0-9]+",
        "\n".join(str(message.get("content", "")) for message in messages).lower(),
    )
)
self.memory_observed = self.memory_observed or self._expected_words <= prompt_words
```

把最终 prompt 切成小写词集，检查 `{"cobalt", "lantern"}` 是不是它的子集，同时要求 `outcome.memory_hits > 0`，两个条件都满足才判 `matched`。

词集检查的巧妙在于反证：session-b 的历史里根本没有这句话（它是个全新会话），暗号能出现在 prompt 里，来源只可能是记忆召回。测试主体还把这个反证的前提也写进断言：`process_a != process_b`、`session_a != session_b`。

有一处必须点破，否则这个证明会被追问打穿：两个进程共享同一组 `user_id` 和 `agent_id`（同一次随机 tag 生成，两次探针调用都传同一份）。记忆的身份维度是 user 加 agent，不是 session、也不是 workspace，所以「换了 workspace 换了 session 还能召回」正是这套身份模型的预期行为，而不是意外。想证明的是跨进程持久化和跨会话检索，不是跨用户串味。

### 证据分级不含糊

live 层的状态词表只有六个值，写死在测试的 `_RESULT_STATUSES` 里：`passed`、`skipped`、`inconclusive`、`failed`、`provider_failure`、`infrastructure_failure`。探针把异常按类型映射进去（认证/限流/API 错误算 provider 失败，超时/连接/httpx 算基础设施失败），子进程返回的 JSON 还要过一次 schema 校验，形状不对直接判 `infrastructure_failure`，不许一个畸形工件冒充通过。

`scripts/verify_continuity.py` 的判定同样严：确定性层要求 `passed > 0` 且 failed / errors / skipped / xfailed / xpassed 全为零；`--live-mode off` 跑出来的结果标 `partial` 而不是 `passed`。这两层合起来就是 M3 那个数字的内容，命令 `make verify-continuity`。

## 八、取舍：为什么不做 X

**为什么 JSONL 追加，不是 JSON 整写？** 第二节算过账：追加崩溃安全（最多损坏一条半行，且可自愈），整写崩在半路整个文件报废；追加天然保序；append-only 让历史前缀稳定，上下文缓存才有得命中。

**为什么追加不推进代际号？** 代际号是「身份换了一代」的信号，只有删除和整写会换代。如果追加也推进，两个正常并发的写者会互相把对方的代际号顶掉，谁也写不进去，栅栏就从「防幽灵」变成了「防同事」。并发追加的正确性由文件锁加内容栅栏保证，`test_concurrent_writers_lose_no_turns` 用真 `multiprocessing` 起两个进程各写一问一答，断言四条消息全在，且每个写者的问答在最终文件里相邻（一个 turn 的消息块不许被另一个写者劈开）。

**为什么没有旧布局迁移？** 刻意的。扁平的旧文件被 `sessions/*/*.jsonl` 的目录 glob 天然忽略，但从不删除（`test_find_most_recent_ignores_old_flat_files` 断言旧文件仍然存在、只是不参与查找）；读取旧全局目录的兼容 shim 也已删除。架构不变量要求 Pico state 保持隔离：宁可让未配置的外部数据静静躺着，也不做隐式搬迁。

**为什么消息不带 turn_id？** 能推导的不存储。顺序由追加序保证，轮次由 role 边界切分，Curator 的 manifest 也是这么建的（id 直接用消息下标）。少一个字段，就少一个「两处不一致怎么办」的问题。代价也认：undo 改写历史后，档案里的旧下标和新历史脱节，文档把它归为「各域独立」的表现。

**为什么删除不级联？** `docs/architecture/state-and-intelligence.md` 的原话值得整段背下：`Arrows show data flow, not a transaction`。随后五条逐一声明：session 保存可以成功而 EverOS store 失败；Curator 档案独立于后来的 session 变更；tracing 可以缺席（它是非侵入的）；删 session 不承诺删语义记忆；Evolver 工件又是独立一域。收尾一句是态度：任何未来的删除、隐私或事务保证，必须逐域显式定义行为。把边界写出来，比一个做不到的「级联删除」承诺可靠。

## 九、真实翻车：栅栏是补上去的

这一节的初稿断言过「session 的五个相关 commit 里没有 fix，只能拿测试名当事故的间接证据」。重新翻 git 之后发现这句是错的，错法很典型：只扫了 commit 标题的类型前缀和 diff 涉及的目录，没打开 PR body 看那次改了什么。

一次专门的并发修复为 Session 写入补上了本章第四节讲的栅栏，目标是让历史变更在并发写者和存储失败下保持原子。

这次修复同时覆盖 `session/manager.py`、`utils/atomic_io.py`、持久化 payload 和 TUI-RPC Session 测试。测试增量大于产品代码增量，说明它修的是一族并发问题，不是一个孤立 bug。

修复之前的 `atomic_io.py` 只有追加与替换两个原语：

```python
def locked_append(path: Path, lines: list[str]) -> None:
    """Append ``lines`` (sans newline) to ``path`` as one contiguous block."""
    ...

def atomic_replace(path: Path, data: str) -> None:
    """Replace ``path``'s content with ``data`` via temp file + os.replace."""
    ...
```

文件锁有了，半行修复也有了，但没有 `expected_epoch`、没有 `validate_existing`、没有 `locked_delete`，代际栅栏和内容栅栏一个都不存在。同一次修复之前的 `save()`，判定走哪条路径的那行是：

```python
if len(session.messages) < session._persisted_count:
    ...  # 整写
else:
    ...  # 追加
```

比条数。撤销两轮再补两轮，或者把一条消息原地改一个字，条数都不变小，于是走追加路径，新内容追在没被撤掉的旧内容后面，磁盘上留下一份内存里从未存在过的历史。现在这一路由 `test_flush_persists_equal_length_message_mutation` 钉住。

相邻模块的同族事故可以佐证这类竞态的普遍性：subagent 的结果曾被路由到错误的会话，外加每次 spawn 泄漏一个 watcher（`48ea5ee`，PR #72）；TUI 取消 turn 时曾丢掉已经流出来的内容（`6aac34f`，PR #85）；跨平台文件锁曾在 Windows 上静默降级成 no-op，并发写直接互相覆盖，`pico/utils/portable_lock.py` 的 docstring 把病史留着（`Replaces the previous fcntl-only lock paths that silently degraded to unlocked on Windows`），session 用的 atomic_io 就是那次修复的直接受益者（第 05 章讲过同一次事故在记忆侧的样子）。

讲这段的姿势：栅栏不是防御性编程的洁癖，每一类栅栏背后都站着一个具体的竞态，而且这个仓库能指出它们是哪一次 commit 装上去的。

## 十、怎么被验证

主战场 `tests/test_session_manager.py`，1575 行 101 项（口径：`uv run --frozen python -m pytest -q --collect-only tests/test_session_manager.py`，工作树 `76d3761`）。分组覆盖：

| 覆盖面 | 代表测试 |
|---|---|
| 追加与重写的切换 | `test_save_appends_instead_of_rewriting`、`test_flush_persists_equal_length_message_mutation` |
| 真 multiprocessing 并发写 | `test_concurrent_writers_lose_no_turns` |
| 崩溃修复四例 | 半行跳过、半行修复、多字节截断、中间坏 UTF-8 fail-closed |
| 代际与内容栅栏 | 三个幽灵测试加 `test_history_rewrite_rejects_messages_appended_after_snapshot` 等十余例 |
| fork | 14 例（血缘、深拷贝、水位继承、标题规则、拒绝空源） |
| undo | 5 例（含永不跨 consolidation 水位、n 钳位） |
| delete 边界 | 10 例（未知 key、缓存懒会话、unlink 失败、不误伤其他会话） |
| 只读目录降级 | `test_read_only_session_directory_can_still_be_loaded` 等 2 例 |

原语层另有 `tests/test_atomic_io.py` 18 项（并发写者零丢失、同路径重建后陈旧追加被拒、代际元数据损坏 fail-closed、跨平台）。导出层 `tests/test_session_export.py` 12 项含篡改检测。TUI 层 `tests/test_tui_rpc_session.py` 1823 行 85 项，覆盖 11 个 RPC 和确认往返的三种窗口期竞态。以上计数同一口径。

门层是 V-O0（M3），`make verify-continuity`。有一件事必须说清楚，否则会被追问打穿：**V-O0 的确定性层不包含 `test_session_manager.py`**。它跑的是 9 个文件（`scripts/verify_continuity.py` 的 `_DETERMINISTIC_TESTS`）：会话连续性 e2e、导出、Curator 上下文引擎、history trimmer、everos pipeline、TUI RPC spine、CLI TUI 命令、em2 backend、verify_continuity 自身，合计 134 项（口径：对这 9 个文件跑 `pytest --collect-only`，工作树 `76d3761`，与 M3 一致）。session 单元测试属于保留套件（M1）的覆盖面。门证明的是「跨组件的连续性语义」，单模块的原子性和栅栏由单元测试证明，两层不重叠也不互相替代。

## 十一、预演追问

**「会话是怎么存的？进程崩了会怎样？」**
每会话一个 JSONL，只追加，每次写 flush 加 fsync。崩溃最多留半行，下次读取跳过坏尾并给会话打上重写标记，下一次保存产出干净文件；中间位置损坏直接报 `StorageCorruptionError`，不猜不修。历史被改写（撤销、清空）才走整写路径，临时文件加 `os.replace` 原子换入。口径补一句：崩溃丢失窗口是「最后一次 save 之后累积在内存里的消息」，而 save 在每轮结束必然发生（`_save_turn` 之后紧跟 `sessions.save`），所以最坏丢一轮，丢的是崩溃时那轮没答完的对话。再补一句边界：`os.replace` 之后没有 fsync 父目录，极端断电下重命名本身可能丢失，结果是回到旧文件，不会出现半新半旧。

**「追加和重写怎么切？为什么不比条数？」**
比前缀。内存里消息列表的前 N 条必须跟磁盘上已持久化的 N 条逐条相等，才允许只追加尾巴。比条数会漏两种情况：撤销两轮再补两轮（条数相同内容全变），把一条消息原地改一个字（条数根本没动）。这两种情况下按条数判定会选择追加，磁盘上就出现一份内存里从未存在过的历史。这不是假想，PR #37 之前的代码就是 `len(session.messages) < session._persisted_count`，现在有专门的等长修改测试钉着。

**「两个进程同时写同一个会话怎么办？」**
三层，各管一件事。互斥：跨进程文件锁（portalocker，POSIX fcntl 加 Windows LockFileEx），进程死了自动释放，锁文件在隐藏的 `.lock/` 目录。代际：`.generation/` 里存一个 epoch，删除和整写推进它，追加不推进；写入时带上自己以为的 epoch，对不上直接 `FileNotFoundError`，「删掉的会话被旧句柄复活」这类幽灵有三个专门测试钉着。内容：追加前持锁重读磁盘，比对元数据、水位、待澄清状态，被并发动过就放弃这次追加。追加之所以不推进代际号，是为了让正常的并发追加不互相顶掉，正确性交给锁和内容校验。有一个真 `multiprocessing` 的测试证明两个写者谁也不丢谁的轮次，而且每个写者的问答在最终文件里相邻。

**「resume 恢复的是什么？」**
恢复的是账本和元数据：全部消息、`last_consolidated` 水位、待澄清状态，外加身份自检（文件里的 key 必须和请求的 key 一致，metadata 缺失时按路径推出的规范 key 也要一致，不一致按损坏处理）。刻意不恢复的东西同样重要：prompt 不恢复，上下文引擎每轮从账本重新装配；运行时对象不恢复，恢复的是数据不是进程。补一个容易加分的细节：CLI 的 `sessions resume` 其实是个纯解析器，它只把 id 或前缀解析成完整 key 并打印，真正的加载发生在 `pico run --session <key>`，前缀有歧义时它会列候选并退出而不是替你猜。这样「恢复」的正确性就归结为「账本的正确性」，而账本已经被三层栅栏保护着。

**「删除会话，数据都没了吗？」**
没有。删除保证的是这个会话的账本失效且不可复活（代际栅栏推进，一切迟到写入被拒），但 Curator 档案、EverOS 语义记忆、trace 是独立的域，各有各的所有权，架构文档明写删除不承诺跨域擦除，并且说了原则：未来任何删除、隐私或事务保证必须逐域显式定义行为。被追问隐私就接着说：这是当前的能力边界，如实声明比假装有级联删除负责，而且级联删除真要做，第一步是给每个域定义「删什么、删到什么程度、失败了算不算删成功」，这三个问题现在都没有答案。

**「怎么证明跨进程连续性，而不是嘴上说说？」**
两个探针。确定性的：三个独立进程接力跑建会话、fork、导出、删除、验收，断言删父不删子、fork 后写入隔离、导出物在源删除后仍可验证；第四个进程直接跑 CLI，断言已删会话 resume 的退出码是 1 且输出里有 `No session matching`。live 的：进程 A 存一句带暗号的话并等记忆队列五个条件同时排空，进程 B 换工作区换会话跑一轮真 turn，用假 provider 检查最终 prompt 的词集包含 `{cobalt, lantern}` 且召回命中大于零；暗号不可能来自 B 的历史，只能来自记忆。要主动交代的前提：A 和 B 共享 user_id 和 agent_id，记忆身份是 user 加 agent 维度，这个证明覆盖的是跨进程持久化和跨会话检索，不覆盖跨用户隔离。两层都在 V-O0 门里，M3 的口径是确定性层 134 项加 1 项必需 live。

**「V-O0 那 134 项都在测 session 吗？」**
不是。V-O0 的确定性层跑 9 个文件，包括会话连续性 e2e、导出、Curator 上下文、history trimmer、everos pipeline、TUI RPC、em2 backend 和门脚本自身，测的是跨组件的连续性语义。session 自己的 101 项单元测试不在这个清单里，它们属于保留套件（M1）。这条分工怎么读：门的清单是显式列举的文件名，跑的是「组件之间的连续性契约」；单模块的原子性和栅栏由单元测试证明，两层各答各的问题。引用 M3 的时候不要顺口说成「session 有 134 个测试」，那是两个不同的口径。

## 口播稿

> Session 是全系统的账本，每会话一个只追加的 JSONL，每次写入 fsync，崩溃最多留半行且可自愈。追加还是重写不看条数看前缀，内存的前 N 条必须跟磁盘的前 N 条逐条相等才允许追加，这条是修出来的，之前按条数判定会让等长修改把脏历史写上盘。并发和生命周期靠三层防线：跨进程文件锁做互斥，代际栅栏防删除后复活和陈旧追加，持锁内容校验防并发漂移，三层各对一类幽灵。生命周期动词语义都抠得很细：fork 是带血缘的全量深拷贝，export 是带 SHA-256 canonical 摘要的可携带信封，undo 按用户消息边界撤整块且不跨蒸馏水位，delete 显式声明不级联删记忆。它和执行层的顺序纪律是账本先于索引，会话先落盘，记忆索引失败不会把已发生的对话变没。连续性不是口头承诺，V-O0 门里有三进程探针加一个真 CLI 进程证明删除、隔离、导出的语义，还有一个跨进程暗号测试证明换了进程换了会话，记忆召回依然把暗号带回 prompt。一百三十四项确定性检查加一项必需 live 检查，命令一条 make verify-continuity。

## 复习路径（10 分钟）

1. 背 key 模型一句话：channel 是维度，身份在 chat_id，格式是时间戳加 6 位随机，文件名就是 chat_id。
2. 讲得出两条写路径的切换条件（比前缀不比条数）、为什么，和追加时补换行那个细节。
3. 三层防线各对一个幽灵：锁对并发覆盖，代际对删后复活，内容校验对并发漂移；再加一句「追加不推进代际号」和它的理由。
4. fork / export / undo / delete 各一句精确语义，delete 必须带「不级联」边界，export 必须带「源删了还能验」。
5. 把 Cobalt Lantern 探针讲成故事：为什么词集检查能证明「来自记忆而非历史」，以及为什么必须主动交代 user_id 相同这个前提。
6. 记住 V-O0 的边界：134 项是 9 个跨组件文件，session 自己的 101 项在保留套件里。
