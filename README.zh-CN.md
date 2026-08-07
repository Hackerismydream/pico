# Pico

Pico 是一个紧凑的 Agent Harness，用来在终端、后台服务、定时任务和消息渠道中
运行可靠的工具型 Agent。所有入口共用同一套 Runtime，因此工作在不同入口之间
切换时，Session、Context、Memory、Tools 和 Tracing 仍然保持连续。

Pico 是通用 Agent Harness，不是 Coding Agent。可选的 Evolver 可以生成可评审的
候选变更和评测证据，但没有明确的人工决定，任何候选都不会被激活。

[English](README.md)

## 为什么选择 Pico

- **一套 Runtime：** CLI、原生 TUI、Gateway、Cron 和 Channels 都通过 Spine
  提交相同的 Turn 契约。
- **持久上下文：** Session 以 JSONL 保存，每次模型调用前都会进行 Context 预算；
  Myna 通过公共 Plugin 接口提供仓库级 Memory。
- **受控工具：** Filesystem、Shell、Web、MCP、消息和 Subagent Tools 共用确认、
  Sandbox 与 Tracing 边界。
- **先有证据，再有结论：** 确定性检查、真实集成、基础设施失败和无结论结果分别
  记录，不相互替代。
- **人工控制的进化：** 候选变更带有 manifest、evaluation、verdict、activation
  决定和 rollback 证据。

## 快速开始

Pico 需要 Python 3.12、`uv`，原生 TUI 还需要 Node.js 22。

```bash
git clone https://github.com/Hackerismydream/pico.git
cd pico
make install build-tui
uv run pico onboard
uv run pico
```

不打开 TUI，直接执行一次 Turn：

```bash
uv run pico run -m "总结这个项目"
```

诊断配置或 Provider 问题：

```bash
uv run pico doctor
```

安装已经构建好的 release wheel：

```bash
uv tool install /path/to/pico_harness-0.1.7-py3-none-any.whl
pico onboard
cd /path/to/your-project
pico
```

## 常用命令

| 目标 | 命令 |
| --- | --- |
| 打开原生 TUI | `pico` |
| 启动交互式 Session | `pico run` |
| 执行一次 Turn | `pico run -m "..."` |
| 配置 Pico | `pico onboard` |
| 检查本地环境 | `pico doctor` |
| 查看 Runtime 状态 | `pico status` |
| 管理 Providers | `pico provider ...` |
| 管理飞书、QQ 和企业微信 | `pico channels ...` |
| 启动后台 Gateway | `pico gateway` |
| 管理 Sessions | `pico sessions ...` |
| 管理定时任务 | `pico cron ...` |
| 浏览本地 Skills | `pico skills ...` |
| 查看 Plugins | `pico plugins ...` |
| 打开 Tracing | `pico tracing` |
| 运行可选进化流程 | `pico evolve check\|run\|status\|finalize` |

## Runtime 模型

```text
CLI / TUI / Gateway / Cron / Channel
                  |
                Spine
                  |
             Turn Runner
                  |
             Agent Loop
        / Context / Memory \
      Tools             Providers
                  |
          Session + Tracing
                  |
               Delivery
```

Context Engine 会检索并预算相关状态，而不是直接截断旧消息。关闭 Memory 后，
本地 Skills 仍然可用。Myna 管理自己的仓库绑定和存储，Pico 只通过已安装的
Memory Plugin 契约使用它。

飞书渠道通过真实 Pico bot 的 Gate 管理 live claim。QQ 和企业微信仍是 Beta：
已有确定性契约覆盖，但当前不声明真实收发结果。任何证据只适用于 Gate 记录的
commit 和场景。

## 状态与安全边界

| 范围 | 默认位置 |
| --- | --- |
| 全局配置与 Runtime 数据 | `~/.pico` |
| 前台项目 | 当前目录 |
| 前台项目状态 | `~/.pico/projects/<project-id>` |
| Gateway Workspace | `~/.pico/workspace` |
| Myna 仓库绑定 | 由 `myna init` 选择的 Myna 配置 |

`PICO_HOME` 可以移动 Pico 的全局根目录。项目状态保存在仓库之外，因此正常启动
不会污染 Git，也不会信任仓库控制的 bootstrap 文件。显式传入 `--workspace` 或
`--config`，表示直接在指定位置上运行。

## 开发

```bash
make install
make ci
```

阅读入口包括 [文档索引](docs/INDEX.md)、[架构说明](docs/architecture/README.md)
和 [开发指南](docs/dev.md)。当前能力结论与证据等级见
[能力证据](docs/feature-evidence.md) 和 [项目状态](docs/project-status.md)。

Pico 仍处于 pre-1.0。接口可能变化；明确标记为 Beta 的能力需要通过更严格的
验证后才能发布。`make ci` 是快速开发门禁，不等同于完整的 release Gate。

## 许可证

Pico 使用 Apache License 2.0。许可证与第三方归因的权威记录见
[LICENSE](LICENSE)、[NOTICES.md](NOTICES.md) 和 [LICENSES/](LICENSES/)。
