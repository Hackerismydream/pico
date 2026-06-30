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

在当前仓库里启动交互模式。默认 provider 是 DeepSeek：

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

## 模型后端

Pico 启动时会读取项目根目录的 `.env`。本地真实 key 放在 `.env`，仓库只保留 `.env.example`。配置优先级是：

```text
显式 CLI 参数 > .env 里的 PICO_* 变量 > 旧环境变量 > 代码默认值
```

Provider 选择的具体顺序是：

```text
--provider > PICO_PROVIDER > 代码默认 deepseek
```

不传 `--provider` 且没有 `PICO_PROVIDER` 时默认使用 `deepseek`。这是推荐配置路径：DeepSeek 的 Anthropic-compatible endpoint 比本地 Ollama 更少依赖本机模型环境，也比 OpenAI-compatible/Anthropic-compatible 代理少一层默认 gateway 假设。其他 provider 仍然保留，可以在 `.env` 里写 `PICO_PROVIDER=openai`、`PICO_PROVIDER=anthropic`、`PICO_PROVIDER=ollama`，也可以显式传 `--provider openai`、`--provider anthropic` 或 `--provider ollama`。

`.env` 会在构建 provider client 前加载，并覆盖当前进程里的同名环境变量。模型名和 base URL 可以通过 `--model`、`--base-url` 临时覆盖；API key 只从环境变量读取。

本地第一次配置：

```bash
cp .env.example .env
```

然后把要使用的 provider key 填进去。`.env` 已经被 `.gitignore` 忽略，不要提交真实 key。

### 推荐配置：DeepSeek

最小配置只需要 key：

```bash
PICO_DEEPSEEK_API_KEY="your-api-key"
```

默认模型和接口是：

```bash
PICO_DEEPSEEK_API_BASE="https://api.deepseek.com/anthropic"
PICO_DEEPSEEK_MODEL="deepseek-v4-pro"
```

所以常规情况下 `.env` 里只填 `PICO_DEEPSEEK_API_KEY` 就能直接启动：

```bash
uv run pico
```

如果你需要临时切模型或代理地址，不必改 `.env`，可以直接覆盖：

```bash
uv run pico --model deepseek-v4-pro --base-url https://api.deepseek.com/anthropic
```

DeepSeek 当前走 Anthropic-compatible Messages API，所以 runtime 里复用的是 Anthropic-compatible client；这只影响 HTTP 协议，不影响 CLI 用法。

### 可选配置：right.codes

right.codes 在 Pico 里有两条可选 provider 路径：

- `--provider openai`：走 OpenAI-compatible `/responses`，默认 base URL 是 `https://www.right.codes/codex/v1`，默认模型是 `gpt-5.4`
- `--provider anthropic`：走 Anthropic-compatible `/messages`，默认 base URL 是 `https://www.right.codes/claude/v1`，默认模型是 `claude-sonnet-4-6`

如果 right.codes 给你的是一把共享 key，推荐只填这一项：

```bash
PICO_RIGHT_CODES_API_KEY="your-right-codes-key"
```

然后按需要选择 provider：

```bash
uv run pico --provider openai
uv run pico --provider anthropic
```

如果你想显式区分两条 provider 的 key，也可以分别配置：

```bash
PICO_OPENAI_API_KEY="your-right-codes-key-for-codex"
PICO_ANTHROPIC_API_KEY="your-right-codes-key-for-claude"
```

不要在 `.env` 里写 `PICO_OPENAI_API_KEY=$PICO_RIGHT_CODES_API_KEY` 这种 shell 展开形式；Pico 的 `.env` 解析器只读取字面量，不展开变量引用。要么只写 `PICO_RIGHT_CODES_API_KEY`，要么把 key 字符串分别填到 provider-specific 变量里。

如果请求 right.codes 返回 `API Key额度不足`，说明协议和 endpoint 已经打通，但当前 key 没有可用额度；换一把有额度的 key，或到 right.codes 后台处理额度。

当前 provider 环境变量：

| provider | base URL | API key | model |
| --- | --- | --- | --- |
| `deepseek` | `PICO_DEEPSEEK_API_BASE`，回退 `DEEPSEEK_API_BASE`，默认 `https://api.deepseek.com/anthropic` | `PICO_DEEPSEEK_API_KEY`，回退 `DEEPSEEK_API_KEY` | `PICO_DEEPSEEK_MODEL`，回退 `DEEPSEEK_MODEL`，默认 `deepseek-v4-pro` |
| `openai` | `PICO_OPENAI_API_BASE`，回退 `OPENAI_API_BASE`，默认 `https://www.right.codes/codex/v1` | `PICO_OPENAI_API_KEY`，回退 `OPENAI_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`PICO_ANTHROPIC_API_KEY`、`ANTHROPIC_API_KEY` | `PICO_OPENAI_MODEL`，回退 `OPENAI_MODEL`，默认 `gpt-5.4` |
| `anthropic` | `PICO_ANTHROPIC_API_BASE`，回退 `ANTHROPIC_API_BASE`，默认 `https://www.right.codes/claude/v1` | `PICO_ANTHROPIC_API_KEY`，回退 `ANTHROPIC_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`PICO_OPENAI_API_KEY`、`OPENAI_API_KEY` | `PICO_ANTHROPIC_MODEL`，回退 `ANTHROPIC_MODEL`，默认 `claude-sonnet-4-6` |
| `ollama` | `--host`，默认 `http://127.0.0.1:11434` | 不需要 | `--model`，默认 `qwen3.5:4b` |

如果有额外的敏感环境变量需要从 trace/report 里脱敏，可以用 `PICO_SECRET_ENV_NAMES` 配置逗号分隔的变量名，或启动时重复传 `--secret-env-name NAME`。

### OpenAI 兼容接口

如果要改用 OpenAI-compatible `/responses` 服务，显式传 `--provider openai`：

```bash
uv run pico --provider openai
```

默认 OpenAI 兼容接口使用 right.codes 的 Codex endpoint：

```bash
PICO_OPENAI_API_BASE="https://www.right.codes/codex/v1"
PICO_RIGHT_CODES_API_KEY="your-right-codes-key"
PICO_OPENAI_MODEL="gpt-5.4"
```

也可以改成其他 OpenAI-compatible 服务：

```bash
PICO_OPENAI_API_BASE="https://your-api.example/v1"
PICO_OPENAI_API_KEY="your-api-key"
PICO_OPENAI_MODEL="gpt-5.4"
```

### Anthropic 兼容接口

如果要改用 Anthropic-compatible 服务，显式传 `--provider anthropic`：

```bash
uv run pico --provider anthropic
```

默认 Anthropic 兼容接口使用 right.codes 的 Claude endpoint：

```bash
PICO_ANTHROPIC_API_BASE="https://www.right.codes/claude/v1"
PICO_RIGHT_CODES_API_KEY="your-right-codes-key"
PICO_ANTHROPIC_MODEL="claude-sonnet-4-6"
```

如果你的服务端对多个兼容接口复用了同一套密钥，`pico` 也支持从 `PICO_ANTHROPIC_API_KEY` 回退到 `ANTHROPIC_API_KEY`、`PICO_RIGHT_CODES_API_KEY`、`RIGHT_CODES_API_KEY`、`PICO_OPENAI_API_KEY` 或 `OPENAI_API_KEY`。

### Ollama

如果要改用本地 Ollama，显式传 `--provider ollama`：

```bash
ollama serve
ollama pull qwen3.5:4b
uv run pico --provider ollama --model qwen3.5:4b
```

## Headless task run

单任务 headless runner 使用同一条 kernel runtime，但运行在隔离 workspace 中。verifier 在 runtime 结束后才执行，不会进入 agent prompt。最小 spec：

```json
{
  "id": "read_fact",
  "workspace": "./fixtures/read_fact",
  "prompt": "Read README and answer with the project fact.",
  "fake_model_outputs": [
    "<tool>{\"name\":\"read_file\",\"args\":{\"path\":\"README.md\"}}</tool>",
    "<final>The project fact is alpha.</final>"
  ],
  "verifier": "python3 -c 'import os; assert os.environ[\"PICO_FINAL_ANSWER\"] == \"The project fact is alpha.\"'",
  "allowed_tools": ["read_file"],
  "max_steps": 4
}
```

`allowed_tools` 是显式 allowlist；省略时默认不给 runtime 任何工具。

运行：

```bash
uv run pico headless task run task.json --runs-root .pico/headless/task-runs
```

输出和 `.pico/headless/task-runs/<task_run_id>/task_run_export.json` 都会区分 `pass`、benchmark `fail` 和 infrastructure `infra_fail`，并引用底层 kernel `runtime_events.jsonl`。

## Headless experiment run

experiment controller 是单任务 runner 上方的控制平面 tracer bullet：它运行一个现有 headless task，并额外写出 experiment id、append-only `experiment_wal.jsonl`、`experiment_export.json`、`experiment_manifest.json` 和 Markdown report。experiment 层只引用 task-run export 和 runtime manifest，不复制底层 RuntimeEvent truth。

最小 experiment spec：

```json
{
  "id": "runtime-lab-smoke",
  "task": "./task.json"
}
```

显式 candidate spec：

```json
{
  "id": "runtime-lab-smoke",
  "task": "./task.json",
  "candidates": [
    {
      "id": "candidate-a",
      "prompt": "Read README and answer with the project fact.",
      "prompt_sha256": "sha256:<hash-of-prompt>",
      "runtime_policy_id": "kernel-readonly-v1",
      "provider_id": "fake",
      "model_id": "fake:default",
      "verifier_id": "readme-verifier-v1"
    }
  ]
}
```

`provider_id` defaults to `fake`, and fake candidates still require `model_id`
values in the `fake:*` namespace for deterministic regression runs. Experiment
candidates may also select `openai`, `anthropic`, `deepseek`, or `ollama` with
an explicit `model_id`; missing live credentials are reported as skipped
infrastructure outcomes, not benchmark failures or passes.

运行：

```bash
uv run pico headless experiment run experiment.json --runs-root .pico/headless/experiments
```

输出和 `.pico/headless/experiments/<experiment_run_id>/experiment_export.json` 会包含 pass、benchmark failure、infrastructure failure、skipped/reused、total run count、scored run count、candidate/prompt/runtime/provider/model/task/verifier identity、usage/cost metadata when available、`task_run_export.json`、`runtime_manifest.json`、`experiment_manifest.json` 和 human-readable report 路径。benchmark score 只用 pass + official verifier failure 计算；provider/API failure、runtime/model execution failure、workspace setup failure、verifier timeout 和 runtime artifact capture failure 都是 infrastructure failure，不计入 benchmark score。benchmark failure 仍返回 0；infrastructure failure 返回非 0。

默认 fake-provider evidence 是 deterministic gate path；真实 provider evidence 是 manual acceptance gate，必须由本机 credentials/network 明确跑出来，缺少 credentials 只会记录 skipped/infrastructure outcome，不会被当成通过。验证已生成 evidence，不重跑 provider：

```bash
uv run pico headless experiment gate .pico/headless/experiments/<experiment_run_id>
```

gate 会读取 `experiment_manifest.json`、experiment WAL、task-run export、task-run facts、runtime events、trace/report、runtime manifest 和 verifier result。它会拒绝缺 runtime event schema metadata、缺 verifier result、缺 task-run export、缺 runtime artifact manifest、或 candidate/prompt/runtime/provider/model/task/verifier identity 不一致的 evidence。当前 MVP 边界仍然是：不做 automatic prompt generation、不做 prompt acceptance policy、不做 runtime-policy A/B claims、不扩 broad tool surface。

## Headless eval grid

eval grid 是单任务 runner 的薄封装：它读取一个小的 config x task 矩阵，每个 cell 都复用 `pico headless task run` 的 kernel runtime、隔离 workspace、verifier 边界和 task-run export。当前可执行 provider 只支持 fake provider，真实 provider 的 usage/cost 字段会先保留在稳定导出结构里，等后续 acceptance gate 接入。

最小 grid spec：

```json
{
  "id": "tiny-grid",
  "tasks": ["./task-a.json", "./task-b.json"],
  "configs": [
    {"id": "fake-default", "provider": "fake"},
    {
      "id": "fake-alt",
      "provider": "fake",
      "fake_outputs_by_task": {
        "task-a": ["<final>alternate answer</final>"]
      }
    }
  ]
}
```

运行：

```bash
uv run pico headless eval grid run grid.json --runs-root .pico/headless/eval-grids
```

输出和 `.pico/headless/eval-grids/<grid_run_id>/eval_grid_export.json` 会包含每个 row 的 task run id、runtime status、verifier status、usage/cost metadata、以及 `runtime_events.jsonl` / trace / report / task-run export 的相对路径。benchmark failure 会以 `status: "fail"` 留在结果里且命令返回 0；infrastructure failure 会以 `status: "infra_fail"` 留在结果里且命令返回非 0。

## Kernel live acceptance

新 kernel runtime 的真实 provider 验收不在默认测试里跑。CI/local 自动 gate 继续使用 fake provider：

```bash
uv run pytest tests/test_runtime_kernel.py tests/test_projection_acceptance.py tests/test_kernel_acceptance.py tests/test_headless_task.py tests/test_headless_experiment.py -q
```

这组 fake-provider 测试覆盖 CLI no-tool、CLI read-only-tool、headless no-tool、headless read-only-tool 和 experiment control-plane tracer bullet，并只断言外部 `runtime_manifest.json`、`runtime_events.jsonl`、`trace.jsonl`、`report.json`、task-run export 和 experiment WAL/export/report contract。

live-provider 是真实验收 gate，需要 provider key 和网络。它不会被默认测试套件触发；缺少真实 provider key 时命令返回非 0，并输出 `status: "skipped"`，不会把未运行的 live acceptance 当成通过。

No-tool 验收：

```bash
uv run python3 scripts/run_kernel_acceptance.py --provider deepseek --scenario no-tool
```

Read-only-tool 验收：

```bash
uv run python3 scripts/run_kernel_acceptance.py --provider deepseek --scenario read-only-tool
```

一次跑完整 live gate：

```bash
uv run python3 scripts/run_kernel_acceptance.py --provider deepseek --scenario all --artifacts-root .pico/kernel-acceptance
```

输出是 JSON，同时会写入 `.pico/kernel-acceptance/<acceptance_run_id>/live_acceptance.json`。每个 scenario 都必须检查：

- `runtime_status: "completed"` 和 `status: "passed"`。
- `final_answer` 与 `runtime_manifest.json` 里的 export projection 一致。
- `finish_reason` / `provider_status` / `provider_metadata` 存在。
- `artifacts.runtime_events`、`artifacts.trace`、`artifacts.report`、`artifacts.manifest` 指向的文件存在。
- `runtime_events.jsonl` 包含 `invocation_start`、`user_input`、`model_output`、`final_answer`、`terminal_status`。
- read-only-tool scenario 还必须包含 `tool_call_requested`、`tool_permission_decision`、`tool_result`，并在 manifest export / report 里看到 read-only `read_file` 的 allow + ok 证据。

Headless experiment live-provider gate uses the experiment controller instead of
the lower-level kernel acceptance harness:

```bash
uv run python3 scripts/run_headless_experiment_acceptance.py --provider deepseek --runs-root .pico/headless/live-provider-acceptance
```

It writes `.pico/headless/live-provider-acceptance/headless_experiment_acceptance.json`
plus experiment/task-run artifacts for one no-tool task and one read-only-tool
task. Exit code `2` means credentials were missing and the run was skipped;
exit code `1` means infrastructure failed; exit code `0` means both verifier
checks passed.

## Kernel default gate

`pico` 的默认 runtime 是 `--runtime auto`。auto 不会因为代码里存在 kernel runtime 就直接切过去；它只读取本地 release-candidate manifest，确认验收 artifact 通过后才默认使用 kernel。manifest 缺失或 gate 失败时，CLI 会回退到 legacy runtime。显式 `--runtime legacy` 会一直保留，显式 `--runtime kernel` 可用于开发调试。

默认 manifest 路径：

```bash
.pico/kernel-release-candidate.json
```

也可以显式指定：

```bash
uv run pico --kernel-release-candidate .pico/kernel-release-candidate.json "summarize this repo"
```

一个 kernel-runtime release candidate 必须同时证明四类 gate：

- `fake_provider_tests`：记录通过的 fake-provider 回归命令，并覆盖 `tests/test_runtime_kernel.py`、`tests/test_projection_acceptance.py`、`tests/test_kernel_acceptance.py` 和 `tests/test_headless_task.py`。
- `live_provider_acceptance`：引用真实 provider 的 live acceptance JSON artifact，且 `no-tool` 和 `read-only-tool` scenario 都为 passed；每个 scenario 的 runtime events、trace、report、manifest、final answer、provider metadata 和 tool evidence 都必须能从本地 artifact 重放。
- `projection_inspection`：引用 `uv run pico --runtime kernel --inspect-run <run_id> --inspect-view all` 产出的本地 inspection JSON，证明 ledger、session、trace、report、export 和 artifact projection 都可重放。
- `headless_single_task`：引用 `pico headless task run` 的 `task_run_export.json`，证明 headless 单任务在 kernel runtime 下通过、verifier 边界受保护、默认工具策略 fail-closed。

legacy fallback 仍用于三种情况：没有 release-candidate manifest；manifest 指向的 artifact 失败、缺失或格式不对；以及迁移窗口里需要显式比较旧 runtime 行为的场景。

## 常用交互命令

- `/help`：查看内置命令
- `/memory`：查看提炼后的工作记忆
- `/session`：查看当前会话文件路径
- `/reset`：清空当前会话状态
- `/exit` 或 `/quit`：退出 REPL

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

## 开发

常用本地检查：

```bash
uv run pytest tests -q
uv run ruff check pico tests scripts
```

内部代码现在按较轻的边界拆分：`pico/evaluation/` 放 benchmark 和 metrics，`pico/providers/` 放模型 provider client，`pico/features/` 放可选运行时能力。新代码应直接使用这些包路径；旧的 `pico.evaluator`、`pico.metrics`、`pico.models` 和 `pico.memory` import 不再作为公共入口保留。
