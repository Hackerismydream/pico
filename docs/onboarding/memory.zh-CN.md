# Myna 记忆首次配置

Pico 负责运行 Turn，Myna 负责绑定仓库、保存来源和在后续 Turn 前生成 Recall Context。两者通过已安装的 `myna-memory` Plugin 组合，Pico 不会把 Myna 代码内置进自己的 wheel。

## 向导会做什么

在 `pico onboard` 第 2 步，Pico 会：

1. 校验装入的 Plugin 是否真的来自 `myna-memory`。
2. 请 Myna 预览初始化计划。
3. 显示 Workspace、repository key、runtime root 和即将创建的路径。
4. 在你确认后应用一次性 consent token。
5. 启动完整 Runtime 执行第一条 Turn。

这个初始化只建立仓库绑定与 runtime root：

- 不扫描或导入历史会话。
- 不安装 Codex 或 Claude Code Hook。
- 不把密钥写入仓库绑定。

## 手工配置与验收

不使用 Pico 向导时：

```bash
cd /path/to/your-project
myna init
myna doctor --live --strict
```

然后确认 Pico 选中了 Myna：

```bash
pico plugins
pico doctor --probe
```

## 明确关闭 Memory

还没有 Myna wheel，或者当前仓库不需要记忆时：

```bash
pico onboard --skip-memory
```

有效配置是 `memory.backend = null`。Local Skills 仍然可用。不要把缺少 Myna Plugin 当作“自动关闭记忆”；当 `memory.backend = "myna"` 时，Pico 会 fail closed。

## 制品边界

源码中存在 Adapter、Plugin identity 校验与安装组合测试，不等于公开用户已经能从稳定制品源安装 Myna。发布时应在同一 Pico release 中提供兼容的 `pico_harness` 和 `myna_memory` wheel，安装脚本会把它们组装到同一工具环境。
