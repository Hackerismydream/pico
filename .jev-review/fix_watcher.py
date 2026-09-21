from pathlib import Path
import sys

root = Path(sys.argv[1])

def replace(name, old, new, count=1):
    p = root / name
    text = p.read_text()
    if text.count(old) != count:
        raise RuntimeError(f'{name}: unexpected patch anchor {old[:80]}')
    p.write_text(text.replace(old, new))

replace('pico/agent/context/builder.py', '        start_watcher: bool = True,', '        start_watcher: bool = False,')
replace('pico/agent/context/builder.py',
    '    构造时区分 ``workspace`` 与可选 ``state``：前者是执行目录，后者存储 Memory、Skill 与\n    Bootstrap；同时可注入 fake clock 让长期 Benchmark 的 Runtime Time 与 Session timestamp\n    一致。LocalSkillCatalog 的 Watcher 可关闭，避免测试启动后台任务。',
    '    构造时区分 ``workspace`` 与可选 ``state``：前者是执行目录，后者存储 Memory、Skill 与\n    Bootstrap；同时可注入 fake clock 让长期 Benchmark 的 Runtime Time 与 Session timestamp\n    一致。默认构造不启动原生文件监听线程；AgentLoop 在 Runtime 启动时接管 Watcher，\n    并在关闭时停止。显式 start_watcher=True 的独立调用方须自行停止监听。')
replace('pico/agent/loop/main.py',
    '            await self._connect_mcp()\n',
    '            await self._connect_mcp()\n            self.context.skills.start_file_watcher()\n', count=2)
replace('pico/agent/loop/main.py',
    '            tasks = tuple(self._personalization_tasks)\n            if tasks:\n                await asyncio.gather(*tasks, return_exceptions=True)\n            await self.close_mcp()\n            self._closed = True\n',
    '''            try:
                tasks = tuple(self._personalization_tasks)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await self.close_mcp()
            finally:
                from pico.spine._barrier import finish_barrier

                await finish_barrier(asyncio.create_task(self._stop_skill_watcher()))
            self._closed = True

    async def _stop_skill_watcher(self) -> None:
        """停止并确认原生 Skill 监听线程退出，失败时保留句柄供再次关闭。"""
        stopped = await asyncio.to_thread(self.context.skills.stop_file_watcher)
        if not stopped:
            raise RuntimeError("Skill file watcher did not stop within the shutdown deadline")
''')
replace('pico/memory_engine/skill_local/watcher.py',
    'Daemon 在 Process Exit 自动清理，显式 :meth:`stop` 用于 Tests/Clean Shutdown。Scope 刻意 Workspace-only，',
    '原生监听线程必须显式 :meth:`stop` 后再退出 Python，Daemon 标记不提供安全清理。Scope 刻意 Workspace-only，')
replace('pico/memory_engine/skill_local/watcher.py',
    '''    def stop(self, timeout: float = 1.0) -> None:
        """Signal Watcher Exit，并在 ``timeout`` 内 Best-effort Join。

        Never Started 或重复调用都安全。无论 Join 是否在时限内完成都会清空 `_thread` Reference；Daemon
        Thread 最终仍可在 Process Exit 被系统回收。
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
''',
    '''    def stop(self, timeout: float = 1.0) -> bool:
        """通知监听线程退出；超时保留句柄，不把发出信号误报为完成清理。"""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            if thread is threading.current_thread():
                return False
            thread.join(timeout=timeout)
            if thread.is_alive():
                return False
        self._thread = None
        return True
''')
replace('pico/memory_engine/skill_local/watcher.py',
    '                stop_event=self._stop,\n',
    '                stop_event=self._stop,\n                rust_timeout=250,\n')
replace('pico/memory_engine/skill_forge/catalog.py',
    '        # 对 ``<workspace>/skills/**/SKILL.md`` 的手动编辑。监视器运行在守护线程中，进程退出时自动清理；',
    '        # 对 ``<workspace>/skills/**/SKILL.md`` 的手动编辑。原生守护线程必须由资源所有者显式停止；')
replace('pico/memory_engine/skill_forge/catalog.py',
    '''    def stop_file_watcher(self) -> None:
        """通知 Watcher Thread Exit，并 Best-effort Join。

        从未启动时安全 No-op；有实例时调用其 `stop` 并清空引用，使后续 Start 可重试。返回不携带线程
        退出证明，具体 Join 行为由 `SkillFileWatcher` 实现。
        """
        watcher = self._file_watcher
        if watcher is None:
            return
        watcher.stop()
        self._file_watcher = None
''',
    '''    def stop_file_watcher(self) -> bool:
        """停止监听并确认退出；超时保留实例，避免启动第二个原生监听线程。"""
        watcher = self._file_watcher
        if watcher is None:
            return True
        if not watcher.stop():
            return False
        self._file_watcher = None
        return True
''')
replace('Makefile', 'tests/test_routing_fallback_chain.py -q', 'tests/test_routing_fallback_chain.py tests/test_skill_watcher_lifecycle.py -q')
for name, text in {
    'docs/plan/jev-personalization.md': '''
## 9. 实施中发现的 Skill Watcher 生命周期修复

扩展回归在原 main 和本分支都出现断言通过后退出 139 的故障。代码检查发现：ContextBuilder 默认构造会启动原生 SkillFileWatcher，AgentLoop.close 却没有停止它；原 stop 超时仍清空句柄，也无法证明线程已经退出。

本次把低层 ContextBuilder 默认构造改为无监听副作用；真实 AgentLoop.run / run_turn 启动本地 Skill Watcher，close 在 finally 中用受取消保护的清理屏障停止并确认退出。监听线程的 Rust 等待上限为 250ms；stop 超时保留句柄并返回 False，Catalog 不丢失仍存活的实例，Runtime 不能静默报告关闭完成。独立使用 ContextBuilder(start_watcher=True) 的调用方仍须明确停止监听。

新增生命周期测试包括真实 Turn 启停、其他资源关闭失败、调用方取消、超时保留句柄、真实文件变动仍可刷新，以及子进程正常退出。它们不通过禁用所有监听、跳过旧用例或 os._exit 掩盖退出问题。这个修复独立于 Jev，必须在实验四组共用。
''',
    'docs/evaluation/jev-personalization.md': '''
## 10. 实验前的退出完整性要求

实施阶段还发现原 main 的 ContextBuilder/SkillFileWatcher 生命周期缺口：部分回归可显示 passed，但 Python 随后以 139 退出。新的 Runtime 显式接管监听启动和停止；此修复与严格 Schema、Origin、路由无证据回退一起进入所有实验组，不算 Jev 收益。

Codex 复核时必须同时确认 pytest 断言、进程退出码与资源关闭结果。不得把“全部断言通过后崩溃”标为测试通过，不得用 os._exit 绕过解释器终结来制造正常退出。最终已执行结果以 PR 改动报告和绑定 commit 的验证记录为准。
''',
}.items():
    p = root / name
    p.write_text(p.read_text() + text)
print('Applied bounded watcher ownership repair; no live API calls.')
