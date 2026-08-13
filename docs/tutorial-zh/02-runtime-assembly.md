# 02 Runtime Assembly：一套装配，多 host 复用

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。
> 其中 EverOS 配置路径是已移除实现的历史讲解；当前 Memory 默认与迁移边界以 [Memory 架构](../memory-plugin-architecture.md) 为准。

读完这一篇，你应该能回答：

- 三个入口各自手写装配会烂在哪里，有没有量化证据
- 为什么答案是「一个具体的组合函数」而不是抽象工厂
- 配置加载链的完整优先级，`set_config_path` 为什么必须最先跑
- 环境变量能盖住哪半边配置，盖不住哪半边，为什么
- 三个 host 装配的真实差异表，哪些差异是有意的
- 共享构造之后还剩哪一类漂移，用什么测试兜住
- 「共享了构造还会不会漂移」这个追问怎么答

## 一、问题：同一份配置，CLI 生效，TUI 静默失效

先把名词落地，后面每一节都要用。这一章说的 host，指用户从哪个入口跟 agent 说话：

| host | 怎么启动 | 前端形态 | 代码位置 |
|---|---|---|---|
| REPL | `pico run` | 终端一问一答，回复整段打印 | `pico/cli/agent_commands.py` |
| TUI | 裸敲 `pico`（无子命令时进 TUI） | Node 子进程渲染的全屏界面，回复逐 token 流出 | `pico/cli/tui_commands.py` |
| Gateway | `pico gateway` | 常驻守护进程，从飞书 / QQ / 企微收消息 | `pico/cli/gateway_commands.py` |

（`pico tui` 这个子命令已经删掉了，`tests/test_cli_smoke.py` 里有一条 `test_removed_root_commands_are_unavailable` 专门盯着它不许回来。）

三个入口共用同一个 agent 内核，也就是 `AgentLoop`：读配置、拼 prompt、调模型、执行工具、写会话，全在里面。入口之间的真实差异只在两头，怎么收到用户的话，怎么把回复画出来。中间那一大坨，本该长得一模一样。

重构之前它们并不一样。三个入口各自手写一遍 `AgentLoop` 的构造参数，三十来个参数，三份手抄。结局是必然的：TUI 那份漏了五个，jina_api_key、disabled_tools、context 配置、memory 配置、SkillForge 路由配置。同一份 config.json，命令行里全部生效，TUI 里静默失效。没有报错，没有警告，没有降级提示，用户只会觉得「TUI 里怎么感觉笨一点」。

漏配之所以难发现，是因为它不会抛异常。`AgentLoop` 的这些参数全有默认值：

```python
jina_api_key: str | None = None,
disabled_tools: list[str] | None = None,
context_config: "ContextConfig | None" = None,
memory_config: "MemoryConfig | None" = None,
skill_forge_router_config: "SkillForgeRouterConfig | None" = None,
```
（`pico/agent/loop/main.py` 构造签名节选）

给默认值是对的，不给的话第三方调用者每次都得填满三十几个参数。代价是漏传等于「主动选择了默认值」，运行时无从区分。这类 bug 只有两条出路：要么让人肉眼比对三份参数表，要么让三份变成一份。

主流 harness 走的也是第二条。Claude Code 的 CLI 和 IDE 扩展共用一个 core session 构造，OpenAI Agents SDK 把 `Runner.run` 做成唯一入口，前端只挑 streaming 与否。抽公共构造这件事本身没有新意，值得学的是 Pico 什么时候动手、动到哪一层为止。

重构的 commit（`07cfdff`，PR #38）给这个病做了量化，PR 描述里的原话是：measurement found 21 byte-identical parameter mappings across all three hosts. The previous layouts contained 63 repeated mapping occurrences; shared composition removes 42 repeated edges。21 个字节级完全相同的参数映射，重复出现 63 次，集中之后消掉 42 条重复边。

这两个数字要背下来，因为它们回答的是一个比 Pico 大得多的问题：什么时候该抽公共代码。答案不是「看起来重复了」，是数出来重复了。仓库把这条写进了工程经验清单（`docs/evolution.md` 第 6 条）：Use shared composition only after measuring duplication... it removed real drift without creating a speculative framework。

朴素方案有两个方向，各有各的死法。复制粘贴的死法就是上面这份病历。另一个方向是抽一个抽象工厂加生命周期接口，仓库明确拒绝了这条路，PR #38 的原话是 Avoid a RuntimeFactory, generic lifecycle protocol, or generic Tool lifecycle interface。`CONTEXT.md` 还立了词条级的命名禁令：

> **Runtime Assembly** (`cli/_runtime_assembly.py`) ... _Avoid_: "Runtime factory" or "lifecycle Interface" — this is one concrete composition with three real host consumers, not an implementation hierarchy.

把命名禁令写进术语表这件事有点极端，但它挡住的是一类真实的滑坡：一个具体函数一旦被叫成「工厂」，下一个人就会给它加注册表、加插件点、加抽象基类，最后没人敢删。

## 二、机制一：一个函数，29 个参数

`assemble_runtime()`（`pico/cli/_runtime_assembly.py`）是那个具体函数。装配顺序固定，四步：

```python
def assemble_runtime(
    config: Config,
    pico_config: PicoConfig,
    *,
    provider: Any,
    cron_service: Any,
    interactive: bool,
    router: Any = None,
    session_manager: SessionManager | None = None,
) -> RuntimeAssembly:
    from pico.agent.loop import AgentLoop
    from pico.cli._plugin_stack import (
        build_plugin_registry,
        build_plugin_tools,
        maybe_build_memory_backend,
    )
    from pico.session.manager import SessionManager

    if session_manager is None:
        session_manager = SessionManager(config.workspace_path)
    plugin_registry = build_plugin_registry(pico_config)
    backend = maybe_build_memory_backend(
        config.workspace_path, pico_config, registry=plugin_registry,
    )
    plugin_tools = build_plugin_tools(
        config.workspace_path, pico_config, registry=plugin_registry,
    )
    defaults = config.agents.defaults
    agent_loop = AgentLoop(
        provider=provider,
        workspace=config.workspace_path,
        model=defaults.model,
        ...                                       # 一共 29 个具名参数
    )
    agent_loop.configure_personalization(defaults.enable_personalization)
    return RuntimeAssembly(
        agent_loop=agent_loop,
        session_manager=session_manager,
        backend=backend,
    )
```

签名里那六个关键字参数，就是三个 host 被允许不一样的全部余地：provider 谁给（REPL 用 `make_provider` 立即建，TUI 用 `make_lazy_provider` 拖到第一次调用）、cron 服务谁给、是不是交互式、要不要模型路由、会话管理器要不要复用一份已有的。除此之外三个 host 没有别的旋钮。

插件注册表建一次用两次，是 PR #38 单独列出的一条修复：Reuse one plugin registry for Gateway backend and tool composition。之前 Gateway 建了两份，等于把插件目录扫两遍、把每个插件激活两次。这类重复不会报错，只会让启动慢一点、让「插件被激活了几次」这种问题变得说不清。

`AgentLoop` 一共 32 个构造参数，装配传 29 个。剩下三个不传，三个理由各不相同，这里必须说清楚，因为其中一个是真实的缺口：

| 参数 | 现状 | 依据 |
|---|---|---|
| `now_fn` | 时间注入缝，默认 `datetime.now`，测试用来钉死时间 | `main.py:317` `self._now_fn = now_fn or datetime.now` |
| `hooks` | EvalEngine 的三个 AgentHook 目前不挂载 | `CONTEXT.md`：the shared Runtime Assembly does not currently add these hooks to `AgentLoop` |
| `strategies` | TokenWise 策略注册表目前没有任何 host 传入 | `install_from_config` 全仓只被 `tests/test_cli_stacks.py` 和 `tests/test_token_wise_integration_openrouter.py` 调用 |

第三行是诚实边界，不要美化：`pico/cli/_token_wise_stack.py::install_from_config` 这个装配器写好了，能把 `TokenWiseConfig` 翻译成一个装着 CacheOptimizer、UsageTracker 的 `StrategyRegistry`，但在代码基线 `76d3761` 上没有任何 host 调它。于是 `self.strategies = strategies if strategies is not None else StrategyRegistry([])` 落到空注册表，只有开了 tool_search 时 AgentLoop 自己往里塞一个 `ToolSearchStrategy`（`main.py:564`）。第 04 章讲 TokenWise 机制时提到的缓存断点，机制成立、实验有历史数据（M6），但它在当前主干上没有被这条装配路径挂进去。面试里被追到这一层，直接认，比含糊过去安全得多。

装配函数体内的 import 也不是随手写的。四个理由，每个都有实据。

**冷启动。** `litellm` 是 provider 层的重依赖，顶层 import 它会拖慢每一个命令，包括 `pico --version` 这种根本不需要模型的。仓库的对策是 PEP 562 惰性再导出，两个包的 `__init__.py` 里各留了一句注释：

```python
# Lazy re-exports (PEP 562): importing a ``pico.agent`` submodule must not
# eagerly construct ``AgentLoop`` -> litellm, which dominates CLI cold start.
```
（`pico/agent/__init__.py`；`pico/providers/__init__.py` 有一条同源注释）

这条纪律有测试兜着，测法是开一个干净子进程：

```python
def test_cli_import_does_not_pull_litellm() -> None:
    r = subprocess.run(
        [sys.executable, "-c",
         "import pico.cli.commands, sys; assert 'litellm' not in sys.modules"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
```
（`tests/test_cli_smoke.py`）

为什么必须开子进程，注释写了：`sys.modules` 是进程全局的，跑整套 `pytest tests/` 时旁边的测试早把 litellm 导进来了，进程内断言会假失败。这是个可迁移的小技巧，凡是断言「某模块没被导入」的测试，都得在干净进程里做。

惰性化带来的启动收益必须从当前候选重新测量。缺少可复现命令和 commit 绑定的历史数字不能当作当前证据；能使用的证据是上面的子进程测试。

**循环依赖。** `pico.agent` 的包初始化本身就是惰性的（上面那段 `__getattr__`），顶层互 import 会把这份惰性抵消掉，还可能成环。

**可测性。** `tests/test_cli_runtime_assembly.py` 靠 monkeypatch 换掉 `pico.cli._plugin_stack` 的三个函数。函数体内 import 意味着每次调用都重新查一遍模块属性，补丁才打得中；改成顶层 import，名字在模块加载时就绑死了，补丁打在空气上。

**代价与对冲。** 惰性 import 把 `ImportError` / `NameError` 从「进程启动即崩」推迟到「跑到那一行才崩」，所以必须有人替你把每条路都走一遍。`tests/test_cli_smoke.py` 就是干这个的：13 个顶层命令、9 个 `channels` 子命令、2 个 `skills` 子命令，各跑一次 `--help`，断言 exit code 0、stdout 里没有 Traceback、`r.exception is None`。文件头注释说得很直白，它专抓 crash-class 回归，并且点名了一次历史事故：`agent_commands.py` 在 CLI 模块化重构后漏了 `sync_workspace_templates` 的 import。

构造的宽严是不对称的，这一点比参数个数更值得讲。记忆后端 fail-closed，插件工具 lenient：

```python
    try:
        tool = registry.build_tool(name, config=plugin_slice, services=services)
    except Exception as e:
        logger.warning(
            "plugin tool %r factory raised at construction (%s); skipping it.", name, e,
        )
        continue
    # A factory may return None to decline contribution at runtime
    # (e.g. an optional dependency isn't installed). That's a clean
    # opt-out, not a failure — skip it without the warning.
    if tool is None:
        logger.debug("plugin tool %r factory opted out (returned None); skipping it.", name)
        continue
```
（`pico/cli/_plugin_stack.py::build_plugin_tools`）

注意这里分了三档而不是两档：抛异常是意外，warning 记账后跳过；返回 `None` 是插件主动弃权（典型场景是可选依赖没装），只记 debug，不打扰用户；正常返回才收进工具表。同一个文件的 `maybe_build_memory_backend` 反过来，一律上抛，模块 docstring 把边界钉死：An explicit `memory.backend` selection is fail-closed: activation, resolution, and construction errors remain visible to the Runtime host. Only `memory.backend = null` disables Memory。

差别的依据是「用户有没有明确表态」。记忆后端是用户在配置里点名要的，点名了却没起来，静默降级等于骗人；插件工具是扫描目录扫出来的，用户从没点过名，一个坏插件不该让整个 agent 起不来。第 05 章会把这条原则讲透，这里只看它在装配层的落地形态。

## 三、机制二：配置加载链

优先级从外到内，四层，先给全景再逐层解释：

```
PICO_HOME            决定「实例根目录」在哪         → ~/.pico 或自定义
  └── --config       换掉整份配置文件（路径级覆盖）  → set_config_path()
        └── PICO_*   字段级环境变量（只盖 base 那半边）
              └── config.json 本体
                    └── Pydantic 模型默认值
```

`PICO_HOME` 那层只有五行代码，但它决定的东西不止一个：

```python
def get_product_home() -> Path:
    override = os.environ.get("PICO_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / GLOBAL_STATE_DIRNAME
```
（`pico/product.py`）

`--config` 是路径级覆盖，换一份文件，不是改一个字段。它的实现是往模块里写一个全局变量：

```python
_current_config_path: Path | None = None

def set_config_path(path: Path) -> None:
    global _current_config_path
    _current_config_path = path

def get_config_path() -> Path:
    if _current_config_path:
        return _current_config_path
    return get_product_home() / "config.json"
```
（`pico/config/loader.py`）

这个全局变量的影响半径比看上去大。`pico/config/paths.py` 里 `get_data_dir()` 的定义是 `ensure_dir(get_config_path().parent)`，也就是说实例的数据目录跟着配置文件走，cron 任务文件（`get_cron_dir()`）、gateway 单实例锁（`<data dir>/gateway.lock`）全在这条链下面。带 `--config` 起的 gateway 会拿一把独立的锁，能和默认实例并存，这不是巧合，是这条链的直接后果。同一个全局变量也是第六节那次事故的现场。

字段级环境变量这层有个反直觉的边界，面试里问出来很能看出有没有真读过代码。base `Config` 是 `pydantic_settings.BaseSettings`：

```python
    model_config = ConfigDict(
        env_prefix="PICO_",
        env_nested_delimiter="__",
        extra="forbid",
    )
```
（`pico/config/schema.py`，`Config` 类尾部）

所以 `PICO_AGENTS__DEFAULTS__MODEL=gpt-4.1` 能盖住 `agents.defaults.model`。但扩展块（context / tokenWise / skillForge / plugins / memory / runtime / tracing）挂在 `PicoConfig` 下面，而 `PicoConfig` 继承的 `_Base` 是普通 `BaseModel`，不是 `BaseSettings`：

```python
class _Base(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
```
（`pico/config/pico.py`）

没有 `env_prefix` 就没有环境变量通道。`PICO_CONTEXT__FAST_PATH_THRESHOLD` 这种写法不会报错，也不会生效，安安静静地什么都不做。唯一的例外是 tracing，它自己在 `pico/tracing/config.py` 里读 `PICO_TRACING`，走的是手写的 kill switch 而不是 pydantic 通道。真要临时改扩展块的行为，只有 `--config` 换文件这一条路。

schema 分两层还带来一个加载顺序问题。base `Config` 是 `extra="forbid"`，直接把带扩展块的 JSON 喂给它必然炸，所以加载器要先把扩展键 pop 掉：

```python
EXTENSION_KEYS = (
    "context",
    "tokenWise",
    "skillForge",
    "token_wise",
    "skill_forge",
    # CFG-1 additions: each key is listed in both camelCase (preferred
    # by config files) and snake_case (preferred by Python).
    "plugins",
    "memory",
    "runtime",
    "tracing",
)
```
（`pico/config/loader.py`，注释原文还有一句 Add new extension blocks here — one place, no duplication）

9 个条目，7 个扩展块。多出来的两条是 tokenWise / skillForge 的 snake_case 别名，其余五个（context、plugins、memory、runtime、tracing）本身就是单词，camel 和 snake 写法相同，只列一次。这份清单被两处引用：`_migrate_config` 在 base 校验前 pop 它们，`load_pico_config` 再读一遍原始文件把它们捞出来喂给 `PicoConfig`。捞的时候有一条容错：

```python
        for key in EXTENSION_KEYS:
            if key in data and data[key] is not None:
                overrides[key] = data[key]
```
（`pico/config/pico.py::load_pico_config`）

显式写 `"context": null` 等于「用默认值」，不报错。这是给配置模板留的空位，用户把不想开的块留成 null，比删掉更能提示「这里有个东西可以配」。

错误处理分三档，每档背后有一条理由或一次事故。

第一档，JSON 语法错，走默认值但大声警告，同时打 stderr 和日志：

```python
        except json.JSONDecodeError as e:
            # Boot on defaults for a malformed file (a transient mid-write race
            # shouldn't brick callers) but warn LOUDLY -- a persistent syntax
            # error would else revert every setting with no visible cause.
            # Raising instead needs atomic save_config first (separate change).
```

第二档，schema 校验错，直接抛。注释里算了一笔账：

```python
            except ValidationError as e:
                # Schema mismatch is a user/programmer error — surface
                # loudly rather than masking with defaults. Silently
                # using defaults makes "feature X did nothing" debug
                # take 24h instead of 24s.
```

24h / 24s 这个对比是全仓最好背的一句注释。它说的其实是本章第一节那个病：静默降级把一个五分钟的配置问题变成一场跨天的排查。

第三档，读-改-写路径上文件存在但读不了，必须抛 `ConfigReadError`：

```python
    Returns ``{}`` ONLY when the file is absent. A present-but-unreadable file
    raises :class:`ConfigReadError` rather than returning ``{}`` -- returning
    ``{}`` and then writing was the bug that wiped a real config over a lone
    JSON syntax error (e.g. a // comment).
```
（`pico/config/loader.py::read_raw_or_raise`）

这个异常连基类都挑过：它故意不继承 `RuntimeError`，因为 CLI 的写命令外面包了一层 `except RuntimeError`（本来是给 provider OAuth 拒绝用的），继承过去会被那层顺手吞掉。「异常类型的继承关系决定它能不能穿过既有的 catch」，这条在任何代码库都成立。

写盘一律走 temp 文件加 `os.replace` 的原子模式，`pico/config/` 下四个 update 模块各有一份（`update.py`、`update_channels.py`、`update_providers.py`、`update_everos.py`）。反例也在库里，`save_config` 是非原子直写，而且 `config.model_dump(by_alias=True)` 会把全部默认值烘进文件，所以增量更新一律不走它。

`set_config_path` 必须最先跑这件事，是本章的主翻车，放到第六节讲。

## 四、机制三：所有权与三个 host 的差异

共享构造带来一个新问题：这些对象归谁关。`RuntimeAssembly` 是个 dataclass，公开生命周期只有 `start_memory_backend` 和 `close`，所有权全在这两个方法里。下面只保留关闭时序主干，逐阶段的 `None` 分支、日志和异常重试代码以省略号表示：

```python
    async def start_memory_backend(self) -> bool:
        if self.backend is None:
            return True
        if self._backend_start_attempted:
            if self._backend_start_error is not None:
                raise self._backend_start_error
            return self._backend_started
        self._backend_start_attempted = True
        try:
            await self.backend.start()
        except BaseException as exc:
            self._backend_start_error = exc
            raise
        self._backend_started = True
        return True

    async def close(self) -> None:
        async with self._close_lock:
            self.agent_loop.begin_close()
            close_task = asyncio.create_task(self._close_once())
            await finish_barrier(close_task)

    async def _close_once(self) -> None:
        cancellation = None
        if not self._agent_closed:
            try:
                await self.agent_loop.close()
            except Exception:
                ...
            except BaseException as exc:
                cancellation = exc
            else:
                self._agent_closed = True

        if self.call_efficiency is not None and not self._call_efficiency_closed:
            await asyncio.to_thread(self.call_efficiency.close)
            self._call_efficiency_closed = True

        if self.backend is not None and not self._backend_stopped:
            await self.backend.stop()
            self._backend_stopped = True

        if cancellation is not None:
            raise cancellation
```

这段主干里藏了四个决定，逐条拆：

`start` 只试一次并把失败缓存下来。第二次调用直接把原异常再抛一遍，不会重试。理由是记忆后端起不来通常是配置或依赖问题，重试只是把同一个错误多打几遍日志。

`except BaseException` 而不是 `except Exception`。`CancelledError` 在 Python 3.8 之后不再继承 `Exception`，用窄的写法会漏掉取消，导致「取消发生过但 `_backend_start_error` 是空的」这种半死状态。记录之后立刻 `raise`，取消语义不被吞。

`close` 是一条三段式关闭屏障：先让 `AgentLoop.close()` 取消并等待后台 Personalizer 任务，再把 CallEfficiency 账本在线程中刷盘关闭，最后停止 Memory Backend。顺序不能交换；否则已经进入 Provider 边界的 `post_learn` 或偏好提取任务会在账本关闭后补记取消记录，产生「真实调用发生、Call Record 丢失、health 仍显示健康」的假象。

`begin_close()` 在第一个 `await` 之前同步封住并取消 Personalizer 任务，保证已经排进事件循环但尚未运行的任务不能抢在关闭任务前进入 Provider。`finish_barrier` 则让已经开始的关闭不被调用方取消切成半截：它先等 `_close_once` 真正完成，再把原来的 `CancelledError` 向上传播。`_close_lock` 串行化并发关闭；`_agent_closed`、`_call_efficiency_closed`、`_backend_stopped` 三个标志分别记录阶段结果。某阶段失败时，下次 `close()` 只重试没有成功的阶段，不会重复关闭已经完成的资源。

`AgentLoop.close()` 是 Agent 侧的总关闭入口。它先封住新的 Personalizer 后台任务，取消并 `gather` 已登记的任务，再调用 `close_mcp()` 收 MCP 和沙箱执行器：

```python
    async def close(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self.begin_close()
            tasks = tuple(self._personalization_tasks)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self.close_mcp()
            self._closed = True
```
（`pico/agent/loop/main.py`）

归属表：

| 资源 | 归属 |
|---|---|
| Memory Backend 构造 / start / stop | assembly |
| CallEfficiency 账本刷盘 / close | assembly，在 Agent 后台任务收敛之后、Backend 之前 |
| Personalizer 后台任务 | Agent Loop 登记并在 `AgentLoop.close()` 中取消、等待 |
| MCP 连接与沙箱执行器 | assembly 的 close 经 `AgentLoop.close()` 连带关闭 |
| SessionManager、插件工具 | assembly 构造（SessionManager 可由 host 传入复用） |
| Provider、Router、Cron 摆放、outlet、池尺寸、启停时序 | host 各自所有 |

host 之间剩下的差异，全在「怎么收、怎么画」这两头：

| 维度 | REPL | Gateway | TUI |
|---|---|---|---|
| Runner | `AgentTurnRunner(loop, stream=False)` | `GatewayTurnRunner`，非流式；只有 CRON origin 回读文本 | `TuiTurnRunner`，USER 流式；CRON / SUBAGENT 非流式回读 |
| 池 user/system | 1/1 | 4/2（`GatewayConfig.user_pool` / `system_pool` 默认值） | 1/1 |
| Outlet | `CliOutlet`，`Capabilities()`，streaming=False | 每 channel 一个 `ChannelOutletAdapter`，重试次数取 `gateway.send_max_retries`（默认 3） | `TuiOutlet`，`Capabilities(streaming=True)` |
| sink 额外行为 | `TurnFailed` 渲染一行，取消和失败文案不同 | 完成回调 + 非取消失败回投「Sorry, I encountered an error.」+ `tool_failures` 非零时 warning | 先 `close_stream` 再 `wait_idle`，然后发 `message.complete` / `error` |
| Cron 白名单 | `{"cli"}` | 已启用的 IM channel 子集（feishu / qq / wecom 里 enabled 的那些） | `{"tui"}` |

三个 host 的池尺寸差异有代码注释背书，不是拍脑袋：

```python
    # user>1 is safe now that per-turn tool state (message routing, context) is
    # turn-local: concurrent user turns no longer clobber each other's reply
    # target. system>1 lets independent Cron and Subagent turns overlap.
```
（`pico/cli/_gateway_spine.py::build_gateway`）

Gateway 敢开 4 个用户槽，前提是每轮的工具状态已经 turn-local 化了。REPL 和 TUI 保持 1/1 不是因为不敢，是因为一个人对着一个终端，第二个并发槽没有使用者。

Cron 白名单那一行是三个 host 里最容易被问的。`pico/cli/gateway_commands.py` 的注释记着事故现场：

```python
        # Restrict to channels gateway has adapters for. This prevents the
        # gateway from racing REPL and stealing cli-origin reminders that REPL
        # can deliver but gateway can't (REPL stdout is owned by the REPL
        # process, gateway has no cli channel). Without this, you'd see
        # "Unknown channel: cli" warnings + lost REPL reminders when both
        # processes are running.
```

cron 任务存在一个共享文件（`<data dir>/cron/jobs.json`）里，三个 host 都能读到全部任务。谁来执行？没有白名单的时候，先看见的进程就抢走了，而 gateway 抢到一条 `channel="cli"` 的提醒之后根本投不出去，因为 REPL 的 stdout 属于另一个进程。白名单把执行权按来源劈开：谁创建的提醒谁负责。`_build_gateway_channels` 的 docstring 还诚实标了代价：这样一来那个进程关掉之后没有跨进程兜底，「fire at origin, hand off only after the origin exits」是被推迟的设计，不是这个集合能解决的。

teardown 三份闭包完全同构，先停调度器再关投递：

```python
    async def teardown() -> None:
        await scheduler.shutdown(grace=0.0)
        await hub.aclose()
```
（`_repl_spine.py` / `_gateway_spine.py` / `tui_rpc/spine.py` 三处逐字相同）

顺序反过来会让「调度器还在产事件、投递已经关了」，事件掉在地上。第 01 章讲过 Spine 侧的取消语义，这里只是它在三个 host 上的同一个落点。

## 五、机制四：host 生命周期三速写

**REPL。** 装配必须在事件循环里做，注释给了原因：

```python
                    # Build the spine before starting cron: cron jobs submit CRON
                    # turns through this scheduler, and on_job must be wired
                    # before cron.start() so an immediately-firing job has its
                    # callback. Scheduler pins its home loop here (run_interactive is
                    # async) — it must not move to the sync prologue.
```
（`pico/cli/agent_commands.py::run_interactive`）

两条约束叠在一起。`Scheduler` 在 `__init__` 里就把 home loop 钉死了，所以它不能在同步序幕里建；`cron.on_job` 必须在 `cron.start()` 之前接好，否则一个「一分钟后提醒我」的任务如果恰好到点，回调是 None。启动顺序因此是：起记忆后端 → `build_repl` → 接 subagent submit → 接 cron 回调 → `cron.start()` → 起 keep-alive task。

关停顺序是启动的镜像：`cron.stop()` → `agent_loop.stop()` → `teardown()` → 等 keep-alive task 收尾 → `runtime.close()`。先停 cron 是因为倒过来会让 teardown 期间触发的任务向已封印的调度器提交。`runtime.close()` 放在最内层的 `finally` 里，前面任何一步炸了它都会跑。

**Gateway。** 启动就拿单实例文件锁，占用则打印对方 pid 和启动时间后退出：

```python
"""Per-instance single-run guard for the gateway.

A cross-platform advisory lock (portalocker: POSIX ``fcntl`` + Windows
``LockFileEx``) is held for the whole process lifetime, so the OS releases it
automatically on death (incl. SIGKILL) — no stale-lock cleanup is ever needed.
"""
```
（`pico/cli/_gateway_lock.py` 模块 docstring）

「靠 OS 释放，不做过期清理」这个选择值得学。自己写 PID 文件加超时判活，永远要处理 PID 复用、时钟回拨、进程僵死这些边角；advisory lock 把这些全丢给内核，进程无论怎么死锁都会掉。

channel 配置校验刻意放在 Runtime 构造之前，注释一句话说明白：Validate Channel configuration before Runtime construction so a bad adapter policy cannot strand plugin-owned resources。顺序反了的话，`assemble_runtime` 已经建好记忆后端和 MCP 连接，然后 `ChannelManager(config)` 抛异常，那些资源没人 close。

Gateway 没有配置热重载。`/restart` 控制命令的实现是整进程自替换：

```python
                        async def _do_restart() -> None:
                            import os
                            import sys

                            await asyncio.sleep(1)
                            os.execv(sys.executable, [sys.executable] + sys.argv)
```
（`pico/cli/gateway_commands.py`）

那一秒 sleep 是给「Restarting...」这条回复留的投递时间，`os.execv` 会直接把当前进程映像换掉，来不及发出去的消息就没了。配置在新映像里重新读一遍，等于用进程重启换掉了整套热重载机制。唯一活着的热重载是 cron 任务文件，`CronService` 每次 tick 比对 `st_mtime_ns`（纳秒精度，注释说明 float 的 `st_mtime` 会把相隔约 238ns 的两次写合并成一次）。

**TUI。** 前端是 Node 子进程，父进程在 127.0.0.1 的随机端口监听，把地址和一个一次性 token 用环境变量传下去：

```python
    server_sock.bind(("127.0.0.1", 0))
    ...
    token = secrets.token_hex(32)
```
（`pico/cli/tui_commands.py::_spawn_with_rpc_socket`）

`token_hex(32)` 是 32 个随机字节，也就是 64 个十六进制字符、256 位熵。为什么需要它，注释解释得很清楚：

```python
# CROSS-PLATFORM (2026-06-30): switched to a TCP loopback socket bound to
# 127.0.0.1:<ephemeral> because Windows has no usable AF_UNIX in CPython and
# cannot os.dup a socket fd. ... (loopback is reachable by any local process,
# unlike an AF_UNIX file guarded by 0600 perms, so the token restores the trust
# boundary).
```

原来用 unix domain socket，文件权限 0600 就是边界；为了 Windows 换成 TCP loopback 之后，本机任何进程都能连上那个端口，边界没了，token 是补回来的那道。「换传输层的时候，顺带丢掉的安全属性得显式补回来」，这是个比 Pico 大得多的教训。

握手 5 秒超时，超时杀子进程、退出码 3。等待写成一场赛跑而不是一个 sleep：

```python
                done, pending = await asyncio.wait(
                    {
                        asyncio.create_task(handshake_done.wait()),
                        asyncio.create_task(proc_done.wait()),
                    },
                    timeout=handshake_deadline_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
```

三个结局：握手成功、子进程先死、超时。子进程早死的话立刻返回，不用干等满 5 秒。这是超时逻辑的通用写法，把「等待成功」和「等待失败信号」并列成两个可等待对象，而不是只等成功再靠超时兜底。

握手成功之后才起后台服务：

```python
                if not handshake_done.is_set():
                    return False
                # Handshake OK (UI rendered) — bring up the memory backend now, in the
                # background, so its heavy import + lifespan happens after render.
                if runtime is not None:
                    runtime_start_task = asyncio.create_task(_start_runtime_services())
```

`_start_runtime_services` 里是 `runtime.start_memory_backend()` 加 `cron_service.start()`。放到握手后面，是因为记忆后端的 import 和 lifespan 都重，挡在首屏前面用户会看到一个空壳窗口。

代价是失败没地方报，因为这时候还没有活着的客户端连接。所以 TUI 有两个「闩住的错误」，路径不同：

| 失败点 | 闩在哪 | 什么时候抛给前端 |
|---|---|---|
| `_build_tui_runtime()` 构造崩（kwargs 漂移、schema 改名、可选依赖缺失…） | `build_error`，`_agent_loop_factory` 闭包持有 | 第一次 `turn.send` 调 factory 时 |
| `_start_runtime_services()` 后台起失败 | `backend_start_error`，`_await_runtime_ready()` 持有 | `TuiTurnRunner.run` 里 await 它时 |

两条都走 `-32603 internal_error`，data 里带 `reason`（`tui_init_crash` / `runtime_start_failed`）和 `log_path`，前端据此和「没配 provider」那种 `-32008` 区分开。

退出码语义表也值得背，因为它决定了什么算「异常退出」：

```python
def _is_abnormal_child_exit(exit_code: int) -> bool:
    return exit_code not in (0, 129, 130, 143, _RPC_HANDSHAKE_EXIT_CODE)
```

0 正常、129 是 SIGHUP、130 是 Ctrl-C、143 是 SIGTERM、3 是握手超时（这条路径自己已经报过错了）。剩下的才算异常，其中最有名的是 139，硬 SIGSEGV，那正是第七节 lancedb 那题的现场。

## 六、一次真实翻车：加载顺序毁掉的 A/B 实验

回归测试文件的头注释本身就是一份事故报告，原文节选：

> Pre-fix, both subcommands called `load_pico_config()` BEFORE `_load_runtime_config(--config)`. Because `load_pico_config()` reads the module-global `_current_config_path` (which `_load_runtime_config` sets via `set_config_path`), the extension blocks (`skill_forge` / `context` / `token_wise`) silently fell back to `~/.pico/config.json` regardless of the `--config` flag.
>
> Real-world impact: every claweval / PinchBench experiment passing a custom config via `--config` got the user's global skill_forge config instead of the per-experiment one, **making A/B comparisons meaningless**.

机制很平常，把第三节那个全局变量再看一眼就明白：`--config` 靠 `set_config_path()` 写 `_current_config_path`，`load_pico_config()` 通过 `get_config_path()` 读它。两个调用顺序反了，读到的就是 `~/.pico/config.json`。base 配置是好的（`load_config(config_path)` 收显式路径参数），扩展块是错的（`load_pico_config()` 不收参数，只读全局）。半对半错，这是它能活这么久的原因。

后果不平常。benchmark 跑 A/B 的标准姿势就是 `--config variant_a.json` 和 `--config variant_b.json` 各跑一遍，而 skill_forge 恰好是扩展块。两个变体读到的是同一份全局配置，跑出来的差异全是噪声。

修复是三件事叠一起。三个 host 的调用点各贴同一段注释：

```python
        # load_runtime_config must run FIRST: it calls set_config_path() so
        # that subsequent load_pico_config() reads from --config, not the
        # default ~/.pico/config.json. Otherwise skill_forge from --config is
        # silently ignored.
```
（`agent_commands.py` / `gateway_commands.py` 两处逐字相同，TUI 的 `_build_tui_runtime` 里是同样的调用顺序）

然后是两层测试，`tests/test_cli_config_precedence.py`：

- `test_load_pico_config_reads_from_set_config_path`：loader 层的契约。写两份配置，全局那份 `injection_mode="summary"`，自定义那份 `"full_body"`；先不设路径读一次，断言拿到 summary，再 `set_config_path(custom)` 读一次，断言拿到 full_body。
- `test_cli_subcommand_loads_extension_blocks_from_custom_config`：CLI 层的真实回归，对 `run` 和 `gateway` 各跑一遍。把 `load_pico_config` 换成一个「捕获结果然后抛异常短路」的桩，用 `CliRunner` 真的调 `pico run --config X`，断言捕获到的是 full_body。

第二个测试的 fixture 有个细节，教学价值不比测试本身低：

```python
    """Isolate Path.home() AND reset the module-global ``_current_config_path``.

    Without resetting the global, a leaked state from a prior test (or
    the developer's shell) would give false positives — the CLI would
    appear to honor ``--config`` even when the order is wrong.
    """
```

测一个全局变量引起的 bug，测试自己也会被这个全局变量污染。前面某个测试留下的 `_current_config_path` 会让「顺序错了」的代码看起来是对的，测试变成假绿。凡是被测对象含进程级可变状态，fixture 就得把它显式复位，光隔离 `Path.home()` 不够。

教训分两层。表层：调用顺序敏感的 API 要么消灭要么钉死，这里选了钉死加注释加两层测试。深层更值得在面试里讲：配置加载的正确性直接决定实验口径的有效性。一个不报错的加载 bug 能让整批实验数据变成噪声，而且噪声看起来跟真结果一模一样，这是第 11 章的证据体系为什么要把「配置指纹」当回事的直接来源。

同一章的病灶谱系里还有两位。第一位是本章开头的 TUI 漏配五参数，构造层漂移，靠共享装配修掉。第二位是 PR #43 处理的呈现层漂移，PR 描述的原话是 Preserve structured Tool failure state through ToolResult, ToolEvent, and TurnOutcome instead of converting failures into silent completion，工具失败在三个 host 曾经各自被转成一种「成功」。共享装配管不到呈现，这一位只能靠跨 host 契约测试钉住。三个病例连起来是一条完整的论证链：先量化重复，再共享构造，然后发现共享构造只覆盖一半，还得测行为等价。

## 七、取舍：为什么不做 X

**为什么不抽象工厂？** 三个消费者、一份具体组合，抽象没有第四个使用者来摊销成本。仓库的通则写在 `docs/evolution.md` 结尾：A new abstraction or capability earns its place only when it deepens a retained module, removes measured duplication or risk, and comes with a verifier at the same boundary。这题的完整答案是那两个数字：21 个相同映射、63 次重复，先有测量后有共享。反过来说，如果哪天出现第四、第五个 host（比如一个 HTTP API server），重新数一遍再决定要不要抽一层，这才是这条规则的用法。

**为什么共享构造不共享呈现？** 呈现差异是真实的产品差异：终端要整段打印，平台要按 channel 投递并重试，RPC 要发结构化事件。强行统一会造出一个谁都不合身的接口，最后每个 host 都在里面塞 if。选择是构造收敛到一个函数，呈现留在各 host，行为等价靠跨 host 契约测试保证。这也解释了 parity 测试为什么要用同一个脚本化 provider 跑三遍：既然接口不统一，就只能从外部观测量上证明它们一致。

**为什么不做配置热重载？** Gateway 的 `/restart` 是 `os.execv` 自替换，等于用一次进程重启换掉整套热重载。热重载要处理的是「已经建好的对象怎么按新配置改」，而 Runtime 里挂着 MCP 连接、沙箱执行器、记忆后端、cron 定时器，每一个都有自己的重建语义。进程替换把这些问题一次性归零，代价是那一秒钟里在途的消息会丢。cron 任务文件是唯一例外，因为它的重载语义足够简单：读一个 JSON，换掉一张任务表。

**为什么 lancedb 要 hard-exit？** 这题的答案不好看，但要认下来。模块 docstring 写得比任何转述都清楚：

```python
"""Hard-exit past CPython interpreter finalization for native-unsafe runtimes.

Building the agent loop opens a lancedb-backed store, and lancedb starts a
process-global ``LanceDBBackgroundEventLoop`` (Rust/tokio) daemon thread with
no public shutdown hook. Finalizing the interpreter while that native runtime
is still live segfaults (``Py_FinalizeEx``; SIGSEGV, exit 139), masking the
command's real exit code.
"""
```
（`pico/cli/_exit.py`）

判活的方式也讲究，它不看模块导没导入，看线程活没活着：

```python
def lancedb_finalization_hazard() -> bool:
    """Merely importing lancedb is safe — the thread only exists once a connection
    is opened — so key on the live thread, not the imported module."""
    return any(t.name == "LanceDBBackgroundEventLoop" for t in threading.enumerate())
```

命中就 flush stdio 和 loguru，然后 `os._exit(code & 0xFF)` 跳过 finalization。这是「上游依赖的生命周期缺陷只能在自己的边界上兜」的标准形态，而且兜的位置选在 CLI 退出的唯一收口处（`pico.cli.commands.run`），不是散在每个命令里。

## 八、怎么被验证

四层，从窄到宽。

**单元层**（`tests/test_cli_runtime_assembly.py`）。`test_runtime_assembly_preserves_config_and_plugin_parity` 逐字断言两件事。一是四步调用顺序，`registry` 那个哨兵对象在 backend 和 tools 两次调用里都出现，等于把「建一次用两次」钉死了：

```python
    assert calls == [
        ("session", tmp_path),
        ("registry", pico_config),
        ("backend", registry),
        ("tools", registry),
    ]
```

二是完整的 29 项 kwargs 字典，一项不多一项不少（`captured == {...}` 是相等，不是包含）。这个测试用 `@pytest.mark.parametrize` 跑三遍，覆盖三个 host 传进来的那组差异：`("cli_once", False, None)` / `("tui", True, None)` / `("gateway", True, sentinel.gateway_router)`。

说清楚它防的是什么，不要说过头：它钉的是 `assemble_runtime` 这一个函数的输出契约。三个 host 之所以不会漂移，是因为它们只能走这一个函数，不是因为这个测试分别检查了三份 host 代码。防漂移靠的是结构（唯一入口）加契约（逐字断言），两者缺一不可。

同文件还有三条所有权测试，对应第四节那三十行代码：start 失败缓存重抛（`test_runtime_assembly_preserves_memory_start_failure`）、close 重试不双停（`..._retries_agent_close_without_double_stopping_memory`）、取消传播前先停后端（`..._stops_memory_before_propagating_cancellation`）。

**契约层**（`tests/test_runtime_host_contracts.py`）。同一个任务在三个 host 各跑一遍，provider 是脚本化的假 provider，第一轮回一个 `read_file` 工具调用，第二轮回终态文本。断言分两组：

```python
    assert mcp_connections == [{"docs"}, {"docs"}, {"docs"}]
    assert all(item.total_tokens == 6 for item in evidence.values())
    assert all(item.tool_calls == 1 for item in evidence.values())
    assert all(item.tool_failures == 0 for item in evidence.values())
    assert all(required <= item.tool_names for item in evidence.values())
    assert {frozenset(item.tool_names) for item in evidence.values()} == {frozenset(evidence["cli"].tool_names)}
    assert {frozenset(item.provider_tool_names) for item in evidence.values()} == {
        frozenset(evidence["cli"].provider_tool_names)
    }
```

`tool_names` 是 agent 自己注册表里的工具集，`provider_tool_names` 是真正发给模型的 schema 名字集，两个都比，因为「注册了但没发给模型」是一种真实的漂移。越界防护也逐 host 验：读工作区外的文件必须返回 outside allowed directory，在工作区外执行命令必须返回 outside workspace。TUI 还多一条，事件序列精确等于：

```python
        assert types == [
            "message.start",
            "tool.start",
            "tool.complete",
            "token.delta",
            "message.complete",
        ]
```

**安装层**（`tests/integration/test_runtime_hosts_real_llm.py`）。把 wheel 装进隔离 venv，用 venv 的 python 起子进程跑三个 host。这一层的价值在于它能抓到源码树里看不见的问题（打包漏文件、entry point 写错、依赖没声明），代价是必须防住「其实导的还是源码树」这种自欺：

```python
        module_raw = result.get("installed_module")
        if module_raw:
            module = Path(str(module_raw)).resolve()
            if not module.is_relative_to(environment_root) or module.is_relative_to(_REPO_ROOT):
                result["status"] = "failed"
                result["reason"] = "checkout_import_detected"
```

子进程环境是白名单制，不是黑名单：`_probe_environment` 只放行 PATH / LANG / TMPDIR 这类必需变量和几个代理变量，`SSH_AUTH_SOCK`、`KUBECONFIG`、`DOCKER_CONFIG`、`PICO_LIVE_API_KEY` 一律不继承，还硬写 `PYTHONPATH=""` 和 `PYTHONNOUSERSITE=1`。这个 fail-closed 自身有测试（`test_probe_environment_is_fail_closed`），失败证据里带 wheel 的 sha256，日志里的 api key 会被 `_safe_text` 换成 `<redacted>`。

失败分类也做了区分，这一层很多人会忽略：`_parse_probe` 把「子进程没输出 JSON」「输出的不是 JSON」「说 passed 但退出码非零」全部归为产品失败（有测试逐条覆盖），而超时归为 `inconclusive`、启动不了归为 `infrastructure_failure`。基础设施抖动不许算产品通过，也不许算产品失败。

诚实边界：`test_runtime_hosts_from_installed_wheel` 带 `@pytest.mark.external_runtime` 标记，按 M18 的口径它被保留套件显式排除，所以 M1 那 3311 项里没有它。跑在保留套件里的是它的那些「测试的测试」（环境 fail-closed、失败分类、超时分类），探针本身要单独跑。

**live 层**。`test_runtime_hosts_real_llm` 同一套骨架换成真 provider，PR #43 最早记录了真实 DeepSeek 三 host；PR #54 又用 fresh V-P0 wheel 刷新为 1 passed（M5），带 stream / 非 stream / 工具调用 / 非空 usage 四项证据。引用时必须带口径：只证明 PR #54 的 commit 与场景。

这一层的确定性版本还留了一个可背的数字：`test_runtime_hosts_from_installed_wheel` 断言假 endpoint 一共收到 6 次请求，其中 2 次是流式。三个 host 各两轮（第一轮出工具调用，第二轮出终态），流式的那两次全来自 TUI。数字小，但它把「谁流式谁不流式」从表格里的一行字变成了可验证的观测量。

## 九、预演追问

**「三个入口怎么保证行为一致？」**

分两层答，别只答第一层。

构造层：一个共享的装配函数 `assemble_runtime`，29 个参数一处维护，有测试逐字断言整个参数字典和四步调用顺序。三个 host 不会漂移的根本原因是它们只有这一个入口可走，测试负责保证这个入口的输出不变。

行为层：共享构造管不到呈现，我们在这上面吃过亏。工具失败曾经在三个 host 被各自转成三种「成功」，PR #43 才把结构化失败态从 `ToolResult` 一路保到 `ToolEvent` 和 `TurnOutcome`。所以另有跨 host 契约测试，同一个脚本化任务在三处各跑一遍，断言工具集、发给模型的 schema 集、token 总数、工具调用与失败计数、MCP 连接次数、工作区越界防护逐项相等，TUI 还额外断言事件序列精确等于五个事件。再往外一层是把 wheel 装进干净 venv 跑三 host 的安装级探针，带「不许导到源码树」的 fail-closed 检查。

一致性不是靠共享代码承诺的，是靠三层测试证明的。

**「配置优先级是什么？出过什么问题？」**

四层，从外到内：`PICO_HOME` 决定实例根目录；`--config` 是路径级覆盖，换整份文件；`PICO_` 前缀的环境变量是字段级覆盖，用 `__` 表示嵌套；最里面是 config.json 本体和模型默认值。

有个边界我可以主动补：环境变量只盖得住 base 那半边配置。base `Config` 是 `BaseSettings`，配了 `env_prefix="PICO_"`；扩展块挂在 `PicoConfig` 下面，那是普通 `BaseModel`，没有环境变量通道，`PICO_CONTEXT__X` 这种写法既不报错也不生效。唯一的例外是 tracing 自己手写了 `PICO_TRACING` 这个 kill switch。

真实事故直接讲：`--config` 依赖一个必须最先执行的 `set_config_path`，它写的是模块级全局；曾经有两个子命令把扩展配置的加载放在了它前面，于是 base 配置读的是自定义文件、扩展块读的是全局文件，半对半错。后果是每一个通过 `--config` 传实验配置的 benchmark 跑的都是用户的全局 skill_forge 配置，整批 A/B 对比作废。修复是三个调用点各贴同一段注释，加一个 loader 层契约测试和一个 CLI 层回归测试，而且那个测试的 fixture 必须显式复位那个全局变量，否则前一个测试的残留会让它假绿。

还可以补一句错误处理分档：JSON 语法错警告后用默认值，schema 校验错直接抛，注释里算的账是静默用默认值会让「feature X 怎么没生效」的排查 take 24h instead of 24s。

**「为什么不抽一个 AgentFactory / 生命周期接口？」**

先给数字：重构的动机是测出 21 个字节级相同的参数映射、63 次重复出现，集中之后消掉 42 条重复边。是测量驱动，不是审美驱动。

再给边界：抽出来的是一个具体函数，不是抽象层。PR #38 里明写拒绝 RuntimeFactory、generic lifecycle protocol、generic Tool lifecycle interface，仓库的术语表甚至禁止把它叫「Runtime factory」，因为只有三个消费者，能摊销抽象成本的第四个使用者不存在。

收尾给通则：新抽象要么加深一个保留模块，要么消除测到的重复或风险，并且要在同一个边界上带一个验证器，三条都不满足就不该存在。如果以后真出现第四个 host，重新数一遍再决定。

**「TUI 前后端怎么通信，安全怎么做的？」**

Node 子进程，父进程在 127.0.0.1 随机端口监听，地址和 token 通过环境变量传给子进程。token 是 `secrets.token_hex(32)`，64 个十六进制字符、256 位熵，一次会话一个，服务端在任何分发之前校验。

这里有段历史值得讲：原来用的是 unix domain socket，0600 文件权限就是信任边界；为了 Windows 兼容换成 TCP loopback 之后，本机任何进程都能连那个端口，权限边界没了，token 是显式补回来的那道。换传输层顺带丢掉的安全属性必须补回来，这是通用教训。

握手 5 秒超时，超时杀子进程、退出码 3。等待写成「握手完成」和「子进程退出」赛跑加超时，早死的子进程立刻返回而不是干等满 5 秒。

还有一个顺序细节：记忆后端的重 import 和 lifespan 放在握手成功之后的后台任务里做，首屏不等它。代价是失败时还没有活着的客户端可通知，所以做了两个错误闩，构造崩的闩在 `build_error` 由第一次 `turn.send` 抛出，后台启动失败的闩在 `backend_start_error` 由 runner 里的 `_await_runtime_ready()` 抛出，都带 `reason` 和日志路径，前端据此和「没配 provider」区分开。

**「进程关不掉、关闭时报错怎么办？」**

关停纪律是固定顺序：先停后台生产者（cron），再停 agent loop，再关投递（`scheduler.shutdown(grace=0.0)` 然后 `hub.aclose()`），最后 `runtime.close()` 收资源。每步失败记日志继续，不连坐；`RuntimeAssembly` 里两个幂等标志分开维护，`close_mcp` 失败下次还会重试，但记忆后端不会被停第二次。取消是特例，`start` 那里用 `except BaseException` 接住 `CancelledError` 记录后重抛，`close` 那里把 backend 的 stop 放在 `finally`，保证取消传播出去之前后端已经停干净。

真实的硬骨头是 lancedb：它的 Rust/tokio 守护线程没有公开关闭钩子，解释器 finalize 时必然段错误，退出码 139 还会盖掉命令本来的退出码。我们的兜底是在 CLI 退出的唯一收口处检测那个线程是否活着，活着就 flush 之后 `os._exit` 跳过 finalization。判活看线程不看模块，因为光 import lancedb 是安全的，开了连接才起线程。

这题答到「知道哪些失败可以吞、哪些必须硬退、以及为什么兜在边界上而不是散在各处」就够了。

**「多个 Pico 进程同时跑会怎样？」**

三处防护，各解决一个具体冲突。

单实例锁：gateway 启动就拿 `<data dir>/gateway.lock`，advisory lock（POSIX `fcntl` / Windows `LockFileEx`），进程死掉包括被 SIGKILL 时由 OS 自动释放，不做过期清理。锁的位置跟着配置文件走，所以 `--config` 起的实例有自己的锁，能和默认实例并存。

cron 白名单：三个 host 读同一个 `jobs.json`，谁执行按来源劈开，REPL 只认 `{"cli"}`，TUI 只认 `{"tui"}`，gateway 只认已启用的 IM channel。没有这个白名单的时候 gateway 会抢走 cli 来源的提醒然后投不出去，日志里是「Unknown channel: cli」，用户那边是提醒丢了。代价也说清楚：创建提醒的进程关掉之后没有跨进程兜底，这是被推迟的设计不是 bug。

配置隔离：`--config` 换文件的同时换掉整个实例数据目录（`get_data_dir()` 取的是配置文件的父目录），cron 存储、锁文件、媒体目录全跟着走，两个实例不会互相踩。

## 口播稿

> 三个入口共用一个装配函数，这件事的来历比结论有意思。重构前三个 host 手抄同一份三十来个参数的构造，量化下来是 21 个字节级相同的映射、重复出现 63 次，而且 TUI 那份漏了五个参数，同一份配置在命令行生效、在 TUI 静默失效，因为那些参数都有默认值，漏传和显式选默认在运行时分不出来。所以我们收敛成一个具体的组合函数，29 个参数一处维护，测试逐字钉住整个参数字典；但刻意不做抽象工厂，只有三个消费者，投机框架的成本没人摊销，PR 里和术语表里都写死了这条禁令。后来发现共享构造只覆盖了一半，工具失败在三个 host 被各自转成三种成功，于是补了跨 host 契约测试，同一个脚本化任务在三处断言工具集、token 数、越界防护逐项相等，再加一层把 wheel 装进干净 venv 跑三 host 的安装级探针，带「不许导到源码树」的检查。配置侧我们也翻过车，`--config` 靠一个必须最先执行的全局赋值，两个子命令把顺序写反了，base 配置读了自定义文件、扩展块回退到全局文件，结果每一批用 `--config` 传实验配置的 A/B 全是噪声。现在是注释加两层回归测试双保险。这一层的方法论就两句：先测量重复再共享，共享构造之后再用测试证明行为等价。

## 复习路径（10 分钟）

1. 背两个数字和一个病历：21 个相同映射、63 次重复，TUI 漏配五参数，并且答得出「为什么漏配不报错」（参数有默认值）。
2. 讲得出装配四步顺序，以及「registry 建一次用两次」为什么单独列成一条修复。
3. 说得出 29/32 那三个没传的参数各自是什么状态，特别是 `strategies` 目前没有 host 传入这条诚实边界。
4. 把 `--config` 事故讲成完整故事：机制（全局变量 + 顺序）、半对半错的表现、后果（A/B 作废）、三段修复、fixture 复位那个细节。
5. 默写三 host 差异表的三行：runner 流式策略、池尺寸、cron 白名单，各配一句为什么。
6. 记住验证四层和各自能证明什么：kwargs 逐字断言（构造契约）、跨 host 契约（行为等价）、installed-wheel 探针（打包与环境，带 external_runtime 标记不在保留套件里）、live 记录（M5，带口径）。
