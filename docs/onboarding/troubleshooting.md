# Onboarding 故障排查

## `configured Myna plugin is unavailable`

原因：Pico 选择了 `memory.backend = "myna"`，但当前 Pico 工具环境里没有兼容的 `myna-memory` distribution。

处理：

```bash
uv tool list
pico plugins
```

使用经过校验的 Myna wheel 重新组装 Pico，或者显式关闭 Memory：

```bash
pico onboard --skip-memory --reset
```

## `Myna is not ready: ... not a Git repository`

Myna 按 Git 仓库绑定记忆。进入目标仓库后重试：

```bash
cd /path/to/your-project
pico onboard --reset
```

## Provider 预检通过，第一条 Turn 失败

`GET /models` 成功只说明凭证或网络的一部分。真实 Turn 还会验证模型 ID、账户额度、Runtime 和 Memory。

```bash
pico provider test <provider-name>
pico doctor --probe
```

检查模型是否属于当前 Provider，以及代理/VPN 是否能访问对应 endpoint。

## 飞书收不到消息

按顺序检查：

1. 应用是企业自建应用，机器人能力已启用。
2. 事件模式是 WebSocket 长连接，已添加 `im.message.receive_v1`。
3. 新权限与新事件所在的应用版本已发布。
4. `pico channels get feishu` 显示 enabled，App ID 正确，密钥已设置。
5. `pico gateway --workspace "$PWD" --verbose` 仍在运行。
6. 群聊中已 @ 机器人；默认 `group-policy=mention`。
7. `allow-from` 包含当前用户 `open_id`，或在调试期间是 `['*']`。

## Gateway 在运行，但操作了错的仓库

一个 Gateway 进程只有一个固定 Workspace。停止旧进程，并使用目标路径重启：

```bash
pico gateway --workspace /absolute/path/to/project
```
