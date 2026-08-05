# 数字口径表（metrics ledger）

全套教程、话术、简历引用数字的唯一出处。规则：

- 正文和话术**引用本表编号**（如 M1），不复制数值。数值变了只改这里。
- 每个数字绑定它的测量 commit / PR。project-status.md 的原话：「Counts below are tied to the named merged PR and must not be silently reused for a later release commit.」面试里被问「这个数字是当前版本的吗」，答案在「新鲜度」列。
- 弱口径如实标注。数字难看或过时，删数字或标历史，不修饰。

## 版本基线（三个，别混）

- **代码基线 `76d3761`（PR #47）**：全部章节描述的 `pico/` 代码按这个工作树读出。
- **证据基线 `b65f962`（PR #53，2026-07-26 核实）**：验证门清单、门的数字、能力成熟度声明按当时的 main 核实。
- **当前检查点 `a04a512`（PR #57，2026-07-27 核实）**：现行 `main` 的项目状态。PR #54 刷新 fresh-wheel host Gate 与 live DeepSeek V-LP；PR #56 刷新 retained/V-E0 并加入 small-real harness；Issue #21 的 required V-LF 随后真实通过，但仍没有真实 Evolution verdict 或完整 V-R0。

代码基线之后的差异逐条列出，凡引用这些的章节必须注明「晚于代码基线」：

| PR | 带来什么 | 影响哪些章节 |
|---|---|---|
| #48 | V-C0 契约门、V-LF 飞书 harness | 08、11 |
| #49 | 依赖公告修复 | 无 |
| #50 | QQ/WeCom 提为契约验证 Beta、新增 V-S0、channel 证据 schema v1→v2、`ChannelSpec.maturity` 字段 | 08、11 |
| #51 | V-TE0 turn 证据关联门 | 09、11 |
| #52 | V-R0 发布候选门 driver 合入主干，`make verify-release` 开始存在 | 11 |
| #53 | 运行时学习路径文档、证据声明校对 | 无 |
| #54 | fresh V-P0 wheel 驱动 host Gate 1 passed；真实 DeepSeek V-LP 1 passed | 00、02、11 |
| #56 | V-E0 增至 319；retained 增至 3567/52；加入 small-real subject/harness，无真实模型 run | 10、11 |

代码侧的差异集中在三处（`git diff 76d3761 b65f962 -- pico/` 实测）：spine 的调度与投递约 166 行、tracing 约 153 行、channels 约 123 行；memory_engine、session、evolver 无变更。也就是说第 05、06、10 章的代码描述不受影响，第 01、08、09 章在细节上可能已经落后。

**这张表最有教学价值的一条**：第 11 章初稿断言「主干上没有 `make verify-release`」，写作期间被 PR #52 推翻。一份讲证据绑定 commit 的文档，自己的断言被 commit 推进作废，这条记录留着不删。

## 当前可用数字

| 编号 | 数值 | 口径 | 测量命令 | 出处 | 新鲜度 |
|---|---|---|---|---|---|
| M1 | 3311 passed / 46 deselected / 11 warnings | 保留确定性 Python 测试套件（排除 real_llm / llm_judge / real_vm / real_channel / external_runtime / e2e 标记） | `make test-retained` | docs/project-status.md「Evidence freshness」 | **教学历史值，PR #47**；现行值见 M19 |
| M2 | 301 passed | V-E0 evolver 验证门，全 fixture 驱动。证明生命周期与证据逻辑，**不证明真实改进** | `make verify-evolver` | 同上 | **教学历史值，PR #47**；现行值见 M20 |
| M3 | 134 项确定性 + 1 项必需 live EverOS | V-O0 会话/上下文/记忆连续性验证门 | `make verify-continuity` | 同上 | PR #47 |
| M4 | 67 个命令探针 | V-P0 分发验证：wheel 边界精确、sdist 重建等价、安装后命令全通 | `scripts/verify_distribution.py` | 同上 | **PR #42 历史值**；PR #50 后 V-P0 passed，PR #54 fresh wheel 被 host/V-LP 消费，但不能沿用 67 这个计数 |
| M5 | live DeepSeek 走通 CLI/TUI/Gateway | 装出来的 wheel + 真实 Provider 的一条 Turn | `make verify-live-provider` | PR #54 commit body | **PR #54：1 passed，fresh V-P0 wheel**；只证明该 commit 与场景 |
| M6 | 总成本 −50.7%（TokenWise 4 断点）；对照 provider 自动缓存 −50.5% | 缓存放置 A/B：3 变体 × 6 轮，claude-sonnet-4-5 via OpenRouter，completion 极小（28 tokens），驱动路径 `AgentLoop.process_direct` **已移除**，未在 `run_turn` 上重跑 | 见报告 Setup 节 | pico/token_wise/EXPERIMENT_REPORT.md（2026-04-15） | **历史快照（donor 期）**；只能作为机制有效性的历史证据引用 |
| M7 | 6 个候选 label，仅 `runtime` 可过 G5 | Candidate Manifest 词表；skill/prompt/policy/model_profile/route fail-closed | — | docs/project-status.md「Candidate-label support」 | 当前 |
| M8 | 5 个执行面 | CLI / TUI / Gateway / Cron / Channel 共用一个 Runtime 与 Turn 模型 | — | README.md / docs/architecture/README.md | 当前 |
| M9 | 3 个 Channel 适配器 | Feishu / QQ / WeCom（donor 期 12 个，裁至 3；Feishu live-gated，QQ/WeCom Beta） | — | docs/project-status.md | 当前 |
| M10 | V-LF 5 个必需阶段 passed；1 个可选 second-actor 阶段 skipped | 真实飞书入站/出站、附件、MediaOut、WebSocket 重启与 Cron 恰好一次；allowlist 负例、重复抑制和错误回执仍由 V-C0 明确承接 | `make verify-live-feishu` | `.pico/evidence/feishu/feishu-live-report.json` | **Issue #21 closure，2026-07-27；只适用于报告记录的 commit 与场景** |
| M15 | 261 项契约测试（V-C0） | Channel 契约门；判定要求 passed>0 且 failed/errors/skipped/xfailed/xpassed 全为零 | `make verify-channels` | PR #48 commit body | PR #48；**PR #50 后增至 387 项**，引用必须带 PR 号 |
| M16 | 保留套件历史线 3015 → 3089 → 3121 → 3311 | 对应 PR #37 / #42 / #43 / #47，可用作一条上升曲线 | `make test-retained` | 各 PR body | 各自绑定 PR |
| M17 | wheel 与 sdist 重建 wheel 各 361 个文件、摘要一致 | V-P0 的包内容一致性断言；PR #37 时是 358 个文件、47 条命令 | `scripts/verify_distribution.py` | PR #42 commit body | PR #42 |
| M18 | 6 个 opt-in 测试标记 | real_llm / llm_judge / real_vm / real_channel / external_runtime / e2e；保留套件显式排除，属证据边界不是豁免 | — | pyproject.toml；tests/README.md | 当前 |
| M19 | 3567 passed / 52 deselected | 当前 retained 确定性套件 | `make test-retained` | PR #56 commit body | PR #56 |
| M20 | 319 passed | 当前 V-E0；仍为 deterministic/fixture，不是 benchmark 成绩 | `make verify-evolver` | PR #56 commit body | PR #56 |
| M21 | V-C0 387 passed；V-S0 35 selections passed | QQ/WeCom/Feishu Channel 契约、安全与隔离 | `make verify-channels` | PR #50 commit body | PR #50；#22 已关闭 |
| M22 | V-TE0 passed | Turn trace、usage、delivery 与终态关联契约 | `make verify-turn-evidence` | PR #51 commit body | PR #51；#23 已关闭 |

## 待产出数字（blocker 关闭时顺手带出，写进对应章节前先登记到这里）

| 占位 | 来源 | 预期口径 |
|---|---|---|
| M13 | Issue #24（V-R0） | 一个 release commit 上的完整门集合结果 |
| M14 | 首次真实 Evolution Run | 轮数、候选数、K、Gate 通过情况、最终 verdict（accepted/rejected/no-improvement 都是合法结果） |

## 面试引用纪律

- M1-M2 是教学基线历史值，现行检查点改引 M19-M20；M3 仍是 PR #47 的 V-O0 证据；M4、M5、M19-M22 都必须带 PR；M10 必须带 V-LF 报告记录的 commit 与场景；M6 必须带「历史快照、旧驱动路径」。
- 被追问「为什么不刷新」的标准答案方向：门是 commit 绑定的，刷新属于 release Gate（Issue #24）的职责，不做散点刷新，这本身就是证据纪律的卖点。
