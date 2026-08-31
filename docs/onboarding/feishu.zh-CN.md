# 把 Pico 接到飞书

目标：在飞书里给机器人发一条消息，由正在运行的 Pico Gateway 返回真实回复。

Pico 使用飞书 WebSocket 长连接，不需要公网 IP 或 webhook 域名。

## 1. 创建企业自建应用

1. 打开[飞书开放平台](https://open.feishu.cn/)，创建“企业自建应用”。
2. 在应用能力中启用“机器人”。
3. 在“凭证与基础信息”中复制 App ID 和 App Secret。App Secret 只应输入本地 Pico 配置，不要发到群聊、Issue 或截图里。

## 2. 配置权限

在“权限管理”中申请：

- `im:message:send_as_bot`：以机器人身份回复。
- `im:message.p2p_msg:readonly`：接收单聊消息。
- `im:message.group_at_msg:readonly`：接收群里 @ 机器人的消息。
- `im:resource`：可选，发送或读取图片、文件等资源时使用。

权限名以飞书开放平台当前界面为准，可在[权限列表](https://open.feishu.cn/document/server-docs/application-scope/scope-list?lang=zh-CN)中复核。

## 3. 配置事件

1. 进入“事件与回调”。
2. 选择“使用长连接接收事件”。
3. 添加事件 `im.message.receive_v1`。
4. 创建并发布应用版本，然后等待管理员审批。权限或事件变更后，需要再次发布才会生效。

对照飞书官方文档：[长连接接收事件](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/request-url-configuration-case?lang=zh-CN)、[添加事件](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/subscription-event-case?lang=zh-CN)和[接收消息](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive?lang=zh-CN)。

## 4. 在 Pico 中启用飞书

可以在 `pico onboard` 的第 4 步填写，也可以直接运行：

```bash
pico channels enable feishu \
  --app-id "cli_xxxxxxxxxxxxxxxx" \
  --app-secret "$FEISHU_APP_SECRET"
```

如果飞书后台开启了 Encrypt Key 或 Verification Token，把它们一起填入：

```bash
pico channels set feishu \
  --encrypt-key "$FEISHU_ENCRYPT_KEY" \
  --verification-token "$FEISHU_VERIFICATION_TOKEN"
```

检查字段与脱敏后的配置：

```bash
pico channels show feishu
pico channels get feishu
```

## 5. 启动 Gateway，发送第一条消息

Gateway 只处理它启动时选定的 Workspace。先进入想让 Pico 工作的仓库：

```bash
cd /path/to/your-project
pico gateway --workspace "$PWD" --verbose
```

保持这个进程运行，然后：

- 单聊：直接给机器人发消息。
- 群聊：默认 `group-policy=mention`，需要 @ 机器人。

看到 Gateway 日志中出现 inbound accepted，并在飞书里收到回复，才算通路成功。[发送消息 API](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create) 是 Pico 回复时使用的飞书能力。

## 安全收口

Feishu 的 `allow-from` 当前默认是 `['*']`，表示允许任意发件人。公开机器人上线前，应收紧到明确的用户 `open_id`：

```bash
pico channels set feishu --allow-from ou_xxxxxxxxxxxxxxxx
```

修改后重启 Gateway。不要把 App Secret、Encrypt Key 或 Verification Token 写入文档和 Git。

## 可选：开源项目维护 MVP

维护模式把普通群聊、问题策展和代码修复分开：群成员只需正常描述问题，不直接创建 Issue。
配置中的维护者回复一条用户消息并发送 `/issue`，Bot 会读取被回复的消息并生成持久化的本地
Issue Proposal，并用可读标题链接回原始飞书话题；维护者也可以发送 `/issue <问题描述>` 手动整理。
内部 `pi_...` 标识只用于诊断，不作为群聊操作入口。维护者确认后，在原问题下回复 `/fix` 即可进入
修复流水线；也可以显式发送 `/fix <GitHub Issue 编号或 URL>`。Issue Proposal 不会自动发布到 GitHub。
维护任务使用独立 Session 和临时 Git worktree，生成本地 PR Candidate；它不会 Push、创建 PR
或评论 Issue。

Feishu 出站消息会回复触发它的原消息：在普通群中形成 Reply，在话题群中留在同一话题，不再为
每条 Agent 输出新建独立话题。Maintenance Job 至少发送 Base 锁定、复现与修改、Repair Checks、
Clean Verification 和终态；超过 `progressIntervalSeconds` 的阶段会发送低频心跳。
群聊进度使用问题标题而不是内部 `pm_...` Job ID。终态为 `candidate_ready` 时，Bot 会把
`CANDIDATE.md` 和 `candidate.patch` 作为原话题附件发送，维护者不需要进入本机目录寻找 ID。

```json
{
  "maintenance": {
    "enabled": true,
    "repository": "/absolute/path/to/pico",
    "baseRef": "origin/main",
    "allowedChats": ["oc_xxxxxxxxxxxxxxxx"],
    "maintainers": ["ou_xxxxxxxxxxxxxxxx"],
    "acceptanceCommands": ["uv run pytest -q"],
    "runnerConfig": "/absolute/path/to/maintenance-runner.json",
    "progressIntervalSeconds": 120
  }
}
```

Gateway 配置应禁用 `write_file`、`edit_file`、`exec` 和 `spawn`，只负责公开问答。`runnerConfig`
是独立的受限配置：保持默认 Workspace（每个任务由 Repair Worktree 的工作目录绑定）、启用
`restrictToWorkspace`、不启用飞书 Channel，不包含 GitHub 凭证。两份配置都应使用仅运行用户可读
的文件权限。

每个 Candidate 位于当前 Pico 实例数据目录的 `maintenance/candidates/<job-id>/`，至少包含：

- `candidate.patch`：针对固定 Base Revision 的 Patch；
- `manifest.json`：Issue、Base Revision、修改文件、命令、退出码和最终状态；
- `agent.log` 与检查日志；
- `CANDIDATE.md`：供 Maintainer 快速审阅的摘要。

只有干净验证 worktree 中的全部命令通过时，状态才是 `candidate_ready`。Agent 无修改、命令失败、
Patch 无法重放或 Gateway 中断分别保留为 `blocked` 或 `verification_failed`，不能写成修复成功。

Candidate Packet 同时是后续自进化的维护案例证据，但一次成功修复不能直接改写 Skill。先由维护者
提名或聚类多个相似案例，再把候选 Skill 放到未参与归纳的历史 Issue 上独立回放；只有稳定提升且
没有扩大权限边界时，才人工发布到 Skill Registry。
