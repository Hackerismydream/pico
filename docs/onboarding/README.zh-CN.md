# Pico 首次使用

这份指南只做一件事：让你在一个 Git 仓库里收到 Pico 的第一条真实回复。

## 安装

Pico 需要 Python 3.12。原生 TUI 需要 Node.js 22，安装脚本会在系统缺失时安装私有 Node runtime。

当前公开 release 还没有可解析的 Pico + Myna 成对 wheel。从源码体验 Pico：

```bash
git clone https://github.com/Hackerismydream/pico.git
cd pico
./install.sh
```

如果你已经拿到经过校验的两个 wheel，安装脚本可以把 Pico 与 Myna 组装到同一个 `uv tool` 环境：

```bash
export PICO_WHEEL_URL="https://example.invalid/pico_harness-VERSION-py3-none-any.whl"
export MYNA_WHEEL_URL="https://example.invalid/myna_memory-VERSION-py3-none-any.whl"
./install.sh
```

上面的 URL 是格式示例，不是可下载地址。不要从来路不明的地址安装 wheel。

Windows PowerShell 使用 `install.ps1`，环境变量名相同。

## 在目标仓库中完成向导

```bash
cd /path/to/your-project
pico onboard
```

向导按用户能看见的结果排序：

```mermaid
flowchart LR
    A["1. 连接 LLM"] --> B["2. 准备 Myna"]
    B --> C["第一条真实回复"]
    C --> D["3. 选择运行位置"]
    D --> E["4. 接入飞书"]
```

1. 选择 Provider，填入 API Key，再选默认模型。
2. 默认使用 Myna。Pico 会先展示仓库、runtime root 和即将创建的路径；你确认后才会初始化。这一步不导入历史，不安装 Hook。
3. Pico 通过完整 Runtime 发送一条消息。看到 `Agent:` 回复才算首次使用成功。
4. 然后再选是否使用 Sandbox，以及是否接入飞书。

如果没有安装 Myna，向导会明确报错。可以先退出安装 Myna，也可以选择“关闭记忆并继续”。自动化场景使用：

```bash
pico onboard \
  --non-interactive \
  --provider openai \
  --api-key "$OPENAI_API_KEY" \
  --skip-memory \
  --skip-channel \
  --yes
```

`--skip-test` 会跳过第一条付费 Turn。这种情况下，Provider 配置成功不等于模型已经真实回复。

## 验收

```bash
pico doctor --probe
pico run -m "用三句话说明这个仓库做什么"
```

启用 Myna 时，再运行：

```bash
myna doctor --live --strict
```

需要结构化结果时：

```bash
pico doctor --json
myna doctor --format json
```

## 继续配置

- [飞书机器人](feishu.zh-CN.md)
- [Myna 记忆](memory.zh-CN.md)
- [故障排查](troubleshooting.md)
- [给安装 Agent 的操作合同](agent-install.md)
