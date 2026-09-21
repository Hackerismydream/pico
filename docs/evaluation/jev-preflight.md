# Jev 验证前置检查与失败定位

本页是可复用的验证操作规程，不是一次测试报告，也不是付费执行授权。先阅读 [实施方案](../plan/jev-personalization.md) 和 [实验协议](jev-personalization.md)。只有实现合同、进程生命周期和计量均可验证，才进入真实模型实验。

## 1. 三种资格必须分开

- **可审查**：代码、设计、测试与已知限制完整，可由人 review。
- **可合并**：目标 PR 的必要检查已实际执行并通过；新增测试和相关回归进程正常退出；未解决的高影响问题已关闭。
- **可启用**：在可合并基础上，完成独立的语义及端到端实验、预算和数据许可，以及人工决策。配置中的 policy_digest 只是关联标识，不证明实验通过。

默认保持 `agents.defaults.personalization_gate.mode: off`。不要为了制造收益基线而启用原本不用的 Personalizer。

## 2. 先冻结身份，再读结果

记录原始评估 commit、目标 main commit、PR head、实际受测 commit、Python 版本、操作系统、uv 版本、uv.lock SHA-256 和执行命令。只有文件名相同或 PR 标题相同，不能证明测的是同一份代码。

原评估基准为 `75795cec37782c929c55a6ff5381084799ac574d`；本次实现的 main 基线为 `697499a36c349bd0989344fd0dcd4282d23d33a9`。它们是教程变更合并前后的不同 Git 身份，不能把 GitHub 三点 compare 的文件列表误读为两棵最终文件树的直接差异。需要核对最终树时使用 `git diff <base> <head> -- pico tests`，不用三个点。

后续 PR 如果新增源码提交，之前的测试结果仍只绑定旧受测 commit。仅文档提交也应明确说明旧结果覆盖的是运行时代码，不声称新 head 已重新通过 CI。

生成的日志、报告、core dump 和证据包放在仓库外。不要提交本地密钥、配置、用户记忆或原始对话。

## 3. 无凭据、一次性环境中的确定性验证

使用受支持的 Python 3.12 和独立环境；不要复用正在运行的用户 Gateway、Session 或真实 Memory。不得给这个环境配置任何模型凭据或选中的生产配置。先检查测试是否使用 MockTransport / StubProvider，再执行。

在一次性 checkout 中安装锁定依赖，不修改依赖清单或锁文件：

```bash
uv python install 3.12
UV_PYTHON=3.12 uv sync --frozen --extra dev --dev
UV_PYTHON=3.12 uv run --no-sync python -VV
```

安装依赖可能联网，但不得顺便执行模型 probe、下载用户 Memory 或运行付费 benchmark。不要执行 `pico doctor --probe`、`make picobench` 或带 real_llm / llm_judge 标记的测试。

下面的逐模块验证只使用本 PR 的确定性测试及相关回归。EVIDENCE 必须指向仓库外的新目录；每个模块保留退出码，单个失败不会使后面的检查消失，最终命令仍以失败退出。

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${EVIDENCE:?Set EVIDENCE to a new directory outside the checkout}"
mkdir -p "$EVIDENCE"
git rev-parse HEAD > "$EVIDENCE/commit.txt"
git status --porcelain > "$EVIDENCE/worktree-status.txt"
UV_PYTHON=3.12 uv run --no-sync python -VV > "$EVIDENCE/python.txt" 2>&1
failed=0
for module in \
  personalizer_jev personalizer_contract routing_fallback_chain \
  config_routing knn_router call_efficiency cli_runtime_assembly \
  agent_loop_memory_pipeline context_invariants agent_loop_empty_recovery
do
  if PYTHONFAULTHANDLER=1 UV_PYTHON=3.12 uv run --no-sync pytest \
    "tests/test_${module}.py" -q \
    -m 'not (real_llm or llm_judge or real_vm or real_channel or external_runtime or e2e)' \
    --junitxml="$EVIDENCE/${module}.xml" \
    > "$EVIDENCE/${module}.log" 2>&1; then
    rc=0
  else
    rc=$?
    failed=1
  fi
  printf '%s\t%s\n' "$module" "$rc" >> "$EVIDENCE/exit-codes.tsv"
done
exit "$failed"
```

另行执行并保留退出码：`make lint-python`、`make test-python`，以及针对准确 base/head 的 pre-commit 和大文件检查。大文件检查的参数是 Git revision range，不是 pre-commit 的参数：

```bash
uv run --no-sync pre-commit run --from-ref "$BASE_SHA" --to-ref HEAD
make check-large-files COMMIT_RANGE="$BASE_SHA..HEAD"
```

上述代码块是执行规程，不是已运行的证据。完整 retained suite、TUI 和安装包验证仍按仓库既有门禁执行，不能拿十个模块代替全部 release 验收。

## 4. 正确处理“断言通过，进程崩溃”

pytest 打印 `N passed` 只描述断言阶段。若随后退出 139、被信号终止或发生 shutdown 错误，这次命令必须记为失败。通过 make 启动时，外层可能返回 2，而日志中的子进程退出码为 139；两层状态都应保留。

不能使用 `os._exit(0)`、过滤 fatal 日志、删除失败测试、忽略进程返回码或只统计 JUnit passed 来制造绿色检查。

定位应采用以下顺序：

1. 在同一机器、同一 Python 构建和锁定依赖下，分别运行基线与 treatment 的相同现存模块。新增模块单列，不混成不同分母的成功率比较。
2. 逐模块、逐测试及逐 fixture 缩小复现。比较正常导入退出与实际调用后的退出；仅导入成功不能排除使用路径上的原生问题。
3. 捕获 faulthandler、进程退出信号和必要的原生回溯。日志列出某个扩展模块，不等于它就是根因；不能仅凭出现 regex、NumPy 或 charset-normalizer 的名称就归因。
4. 将解释器来源、pytest 插件或单个依赖版本作为独立诊断轴。保留锁定基线，不进行全量升级后把问题消失写成已定位。必要的依赖修复必须通过 uv 并独立 review。
5. 修复后重跑完整命令，要求断言与进程退出都成功。基线也能复现只说明问题不局限于 treatment，不豁免 PR；尤其新增测试进入默认 make 目标后，该目标也必须正常退出。

如果当前执行环境无法复现或缺少原生调试能力，记录准确缺口及下一步，不宣称已修复。

## 5. GitHub 检查与辅助验证的边界

PR 的 CI 状态为 action_required、queued 或未执行时，都不能记录为通过。需要仓库维护者按照 GitHub 显示的具体原因完成操作后，再运行该 PR 的正常检查。

不得修改分支保护、降低检查要求、伪造 commit status，或借其他 workflow 绕过审批。已经存在的辅助验证结果可以用于故障定位，但不能代替目标 PR 的必要检查。

## 6. Codex 在模型实验前应补齐的工程项

先关闭以上验证阻塞，再按实验协议完成 checkout-only A/B/C/D 对照适配器。B（不做前置分类）和 C（普通小模型门控）不是本 PR 已交付的 Runtime 产品开关，不得假装已存在。

评测侧需要 plan/run/rebuild 边界、固定 Trial 分母、隔离状态、独立任务验证、全部调用的预算预留与 ledger 汇总，以及失败/超时/取消/未知 usage 的回归测试。rebuild 必须不触发 Provider、Jev、Memory 或 Tool 调用。不得额外创建第二套 Agent Loop。

先交付不调用模型的冻结计划、成本上界和标注方案。真实 Jev、主模型和普通小模型调用统一需要明确的预算及数据发送许可；shadow 同样会产生费用与延迟。不得把本页或 policy_digest 当作授权。

## 7. Review 结束条件

交付报告分别标明源码提交、实际受测提交、命令退出码、仍未执行的检查、已知阻塞、已实现的独立修复，以及未来实验。真实效果未验证时只能描述接入合同，不能承诺准确率、费用下降或延迟收益。

代码 review 与性能实验 review 是两个决定。通过代码 review 不自动合并，不自动启用 Jev，也不自动通过发布或用户授权。
