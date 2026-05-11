# pico

`pico` 是一个面向代码仓库的轻量本地 coding agent。它直接跑在终端里，先看当前工作区，再用一组受约束的工具去读文件、改文件、跑命令，并把会话状态保存在本地 `.pico/` 目录里。

它更像一个能在仓库里持续工作的命令行助手，不是纯聊天窗口。你可以拿它做代码排查、测试修复、仓库分析，或者让它在当前项目里执行一次性的工程任务。

## 适合做什么

- 在本地仓库里排查测试失败
- 读取当前代码结构并给出修改建议
- 基于现有文件做小步迭代，而不是脱离仓库空想
- 在会话中保留上下文，支持继续上一次工作

## 主要特性

- 包名是 `pico`
- CLI 命令是 `pico`
- 模块入口是 `python -m pico`
- 会话保存在 `.pico/sessions/`
- 每次运行的工件保存在 `.pico/runs/<run_id>/`
- 计划文件保存在 `.pico/plans/`
- 支持普通 REPL 和 Textual TUI 两种交互入口
- 支持本地 Skill System：`.pico/skills/<name>/SKILL.md` 会进入 skill catalog，默认只披露摘要，按需用 `/skill:<name>`、`list_skills`、`load_skill` 渐进加载
- 支持受限 subagent：`Explore` 只读调查，`Worker` 按 `write_scope` 限定写入
- 支持四类模型后端：
  - Ollama
  - OpenAI 兼容 Responses API
  - Anthropic 兼容 Messages API
  - DeepSeek Anthropic 兼容 API

## 使用截图

CLI 帮助信息：

![pico help](assets/screenshots/pico-help.png)

启动界面：

![pico start](assets/screenshots/pico-start.png)

REPL 内置命令与会话路径：

![pico repl](assets/screenshots/pico-repl.png)

## 安装

需要 Python 3.10+。

如果你用 `uv`，直接安装依赖：

```bash
uv sync
```

如果你已经在自己的 Python 环境里工作，也可以直接装成可编辑模式：

```bash
pip install -e .
```

## 快速开始

在当前仓库里启动默认 TUI 交互模式。默认 provider 是 `openai`，默认 base URL 是 right.codes 的 Codex endpoint：

```bash
uv run pico
```

指定另一个工作目录：

```bash
uv run pico --cwd /path/to/repo
```

直接跑一次性任务：

```bash
uv run pico "inspect the test failures and propose a fix"
```

如果当前环境已经安装过包，也可以直接这样启动：

```bash
python -m pico
```

`pico` 无 prompt 时默认就是 TUI。也可以显式指定：

```bash
uv run pico --tui
```

也可以走单独入口：

```bash
uv run pico-tui
```

TUI 不重写 agent 运行逻辑。它复用同一个 `Pico.ask()`，在后台线程执行模型和工具调用，前台显示消息流、工具卡片、审批提示、上下文用量、trace 路径和当前 session 状态。

### Skills

Pico 的 skill 是本地 Markdown 指令，不是远程插件。放在：

```text
.pico/skills/<name>/SKILL.md
skills/<name>/SKILL.md
```

`SKILL.md` 支持 frontmatter：

```markdown
---
name: pytest
description: Run focused pytest coverage.
when_to_use: Python test work.
triggers: pytest, tests
argument-hint: target
context: inline
---

Run `$ARGUMENTS` from `${PICO_SKILL_DIR}` before the full suite.
```

Prompt 里默认只出现 `Available skills` 摘要。完整正文只有两种方式会加载：用户输入 `/skill:pytest tests/test_pico.py`，或者模型先看摘要后调用 `load_skill(name,args)`。如果摘要被预算省略，模型可以先调用 `list_skills(query, limit)` 做目录检索，再精确加载目标 skill。

`context: inline` 的 skill 正文一旦被显式加载，会在下一轮 prompt 的 `skills` section 里完整保留，不被普通上下文预算静默裁掉。`context: fork` 则会在隔离的 Explore subagent 里运行，父会话只拿到执行结果，不把 skill 正文灌回父 prompt。

如果要回到旧的纯文本 REPL：

```bash
uv run pico --repl
```

## 模型后端

Pico 启动时会读取项目根目录的 `.env`。本地真实 key 放在 `.env`，仓库只保留 `.env.example`。配置优先级是：

```text
显式 CLI 参数 > .env 里的 PICO_* 变量 > 旧环境变量 > 代码默认值
```

本地第一次配置：

```bash
cp .env.example .env
```

然后把要使用的 provider key 填进去。`.env` 已经被 `.gitignore` 忽略，不要提交真实 key。

### Ollama

```bash
ollama serve
ollama pull qwen3.5:4b
uv run pico --provider ollama --model qwen3.5:4b
```

### OpenAI SDK / 兼容接口

默认 `openai` provider 使用 OpenAI Python SDK。base URL 默认是 right.codes 的 Codex endpoint，所以 SDK 路径仍然可以走 Right Code 这类中转服务：

```bash
PICO_OPENAI_API_BASE="https://www.right.codes/codex/v1"
PICO_OPENAI_API_KEY="your-api-key"
PICO_OPENAI_MODEL="gpt-5.4"
```

也可以改成其他 OpenAI-compatible 服务：

```bash
PICO_OPENAI_API_BASE="https://your-api.example/v1"
PICO_OPENAI_API_KEY="your-api-key"
PICO_OPENAI_MODEL="gpt-5.4"
```

```bash
uv run pico --provider openai
```

`pico` 默认就是 `openai` provider，所以配置好 key 后也可以直接：

```bash
uv run pico
```

`openai` provider 会把 `--base-url` 传给 SDK。只要中转服务实现 OpenAI Responses 或 Chat Completions 的协议形状，SDK 就能正常走中转。right.codes 的 Codex endpoint 默认使用 Chat Completions；如果你的 endpoint 明确支持 Responses，可以加：

```bash
uv run pico --provider openai --openai-api-mode responses
```

如果需要回到旧的手写 HTTP OpenAI-compatible 适配器，可以使用：

```bash
uv run pico --provider openai-compatible
```

SDK Responses 路径仍然保留 `pico` 的 prompt cache 逻辑。只要 base URL 命中 `openai.com` 或 `right.codes`，运行时会通过 SDK 的 `extra_body` 带上 `prompt_cache_key`，缓存保留策略是 `in_memory`。

Right Code 是我用得比较多的中转站，大家也可以按自己的需求换成别的 OpenAI-compatible 服务。注册链接：

[https://www.right.codes/register?aff=e1617692](https://www.right.codes/register?aff=e1617692)

### Anthropic SDK / 兼容接口

默认 `anthropic` provider 使用 Anthropic Python SDK。base URL 默认是 right.codes 的 Claude endpoint，所以同样可以走 Right Code 中转：

```bash
PICO_ANTHROPIC_API_BASE="https://www.right.codes/claude/v1"
PICO_ANTHROPIC_API_KEY="your-api-key"
PICO_ANTHROPIC_MODEL="claude-sonnet-4-6"
```

```bash
uv run pico --provider anthropic
```

如果你的服务端对多个兼容接口复用了同一套密钥，`pico` 也支持从 `PICO_ANTHROPIC_API_KEY` 回退到 `ANTHROPIC_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`PICO_OPENAI_API_KEY` 或 `OPENAI_API_KEY`。

如果需要回到旧的手写 HTTP Anthropic-compatible 适配器，可以使用：

```bash
uv run pico --provider anthropic-compatible
```

### DeepSeek

DeepSeek 是另一条很实用的 provider。它的价格比较低，接口也比较稳定，适合日常写代码、测试和长时间使用时控制成本。

```bash
PICO_DEEPSEEK_API_BASE="https://api.deepseek.com/anthropic"
PICO_DEEPSEEK_API_KEY="your-api-key"
PICO_DEEPSEEK_MODEL="deepseek-v4-pro"
```

默认 DeepSeek base URL 是 `https://api.deepseek.com/anthropic`，走 DeepSeek 的 Anthropic 兼容接口。如果需要改到代理服务，可以设置 `PICO_DEEPSEEK_API_BASE` 或启动时传 `--base-url`。

如果想明确切到 DeepSeek：

```bash
uv run pico --provider deepseek
```

也可以用快捷参数：

```bash
uv run pico --deepseek
```

DeepSeek 这条链路当前不走 `pico` 的 prompt cache 复用，但胜在稳定和便宜，作为默认 OpenAI/right.codes 之外的低成本方案很合适。

## 常用交互命令

普通 REPL：

- `/help`：查看内置命令
- `/memory`：查看提炼后的工作记忆
- `/session`：查看当前会话文件路径
- `/history`：列出当前工作区的本地 session
- `/resume <id|number>`：恢复某个历史 session
- `/compact [n]`：把旧 history 压缩成持久摘要，保留最近 n 条消息
- `/plan [topic]`：进入计划模式，只允许读工具和写当前 plan 文件
- `/execute`：退出计划模式，回到正常执行
- `/reset`：清空当前会话状态
- `/exit` 或 `/quit`：退出 REPL

TUI：

- `/help`：查看 TUI 命令
- `/clear`：清空当前可见消息流
- `/new`：重置当前会话状态
- `/memory`：查看工作记忆
- `/session`：查看会话文件和事件文件路径
- `/context`：查看最近一次 prompt 的 token 和 section 分布
- `/trace`：查看最近一次运行的 trace/report 路径
- `/agents`：查看 subagent 状态和最近结果
- `/history`：列出当前工作区的本地 session
- `/resume <id|number>`：恢复某个历史 session
- `/compact [n]`：把旧 history 压缩成持久摘要
- `/plan [topic]`：进入计划模式，创建 `.pico/plans/` 下的 plan 文件
- `/execute`：退出计划模式
- `/approval auto|ask|never`：切换当前会话的工具审批策略

## 安全与持久化

`pico` 不会默认把所有动作都放开。像 shell 执行、文件写入这类高风险操作，会受审批模式控制：

- `--approval ask`
- `--approval auto`
- `--approval never`

每次运行结束后，都会在 `.pico/runs/<run_id>/` 下写出这些文件：

- `task_state.json`
- `trace.jsonl`
- `report.json`

这些内容默认只保存在本地，不需要跟仓库一起提交。

## Subagent

Pico 的 subagent 是 runtime harness 的一部分，不是另一个无边界主 agent。主 agent 仍然是 coordinator，负责综合理解、决定下一步和最终完成判断。

当前暴露三个工具：

- `agent`：启动一个 subagent
- `send_message`：继续一个已有 subagent
- `task_stop`：停止一个运行中的 subagent

两类 subagent：

- `Explore`：只读调查，只能搜索、读文件和运行安全的只读命令。
- `Worker`：可执行实现任务，但必须传 `write_scope`，写入超出范围会被 runtime 拒绝。

subagent 结果会以 `<subagent-notification>` 形式回流主会话，同时写入 `task_state.json`、`trace.jsonl`、`report.json` 和 TUI `/agents`。

## 开发

如果装了 Ruff，可以这样检查：

```bash
uv run ruff check .
```
