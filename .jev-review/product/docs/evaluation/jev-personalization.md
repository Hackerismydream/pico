# Jev 偏好快速放行：交给 Codex 的实验协议

状态：NOT_RUN。确定性测试只证明接入合同，不证明 Jev 判断质量。这个文档不是运行授权，不包含 API key。调用真实 Jev 或主模型之前必须获得独立的预算和数据发送授权。

## 1. 先验证问题存在，不要先打开功能

只读核查实际运行配置：Personalizer 是否已经开启，Memory Backend 是否可用，使用的是哪个分类模型。读取完整且健康的 CallLedger 与 trace，估计分类调用次数、费用与首个有效回复等待占比；不能仅凭默认配置或类文件存在推断真实流量。

没有已有使用量，或者取消独立前置分类已经更好时，停止实验，保留 off。不得先启用 Personalizer，再把省下一部分新增开销写成 Pico 的收益。

应先交付一页事实摘要：调用量分母、分类是否产生独立 request、是否存在可验证的多余澄清或漏问、账本覆盖程度，以及是否值得进入模型实验。

## 2. 冻结代码身份与对照轴

记录 PR 最终 head、main baseline、依赖锁 hash、运行机器、地区、主模型及实际返回模型版本。原 `75795ce` / `697499a` 是历史代码身份，不代替最终实验 commit。

把本 PR 的严格 Schema、Cron Origin 和无证据路由修复放进所有实验组。主对照必须是同一修复后的 commit、只改变 gate 或分类策略。否则无法知道改善来自 Jev 还是原 bugfix。

原 commit 的历史 replay 可以单独报告，不和 Jev A/B 的任务分母合并。

| 组 | 明确行为 |
| --- | --- |
| A / current-classifier | 旧主模型前置分类，gate off；其余配置与目标已启用部署一致 |
| B / no-preclassification | 新请求不调用独立前置分类，主 Agent 使用现有上下文与 ask_user 自行判断；不要把所有 Personalizer 副作用也一起关闭 |
| C / small-model-gate | 普通小模型，使用同一 state、三个问题、相同 Choice 组合与回退；结构化输出须严格本地校验 |
| D / jev-gate | `jev-1.13.0`，同一 state 与组合；不合格回 A 的分类模型 |

B、C 当前不是公开产品能力，需要 Codex 在 checkout-only 评测适配器中实现。不要为了实验给 Runtime 增加第二套 Agent Loop。可使用 `benchmarks/picobench` Trial Host / `assemble_runtime` 的既有边界；禁止 Runtime 反向 import benchmarks。

## 3. 判断集：200 条是起步规模，不是统计保证

建议 60 条调整集、140 条封存验证集。以原始会话或任务族为 cluster 分组；同一请求的改写、翻译和轻微变体不得跨集合。先去重，再固定 split，记录每条输入的 hash。

语言分布以真实使用量为依据；没有使用量时，预先设定以中文为主的实验分布，例如中文 100、混合 60、英文 40，不能在看结果后改权重。每条另标以下属性，可交叉覆盖而不是每类独立增加分母：

- 明确请求、存在合理默认、确实缺不可替代偏好、已知记忆覆盖、近期对话覆盖。
- 多意图、代词追问、同一偏好的新旧冲突、要求“不要替我选”、问题已回答。
- pending clarification、Cron、Subagent、媒体依赖、过长输入、非文本历史。
- 证据不足、复杂推理、长无关干扰、提示注入及试图要求模型替代授权判断的输入。

后三类应验证“不适用时退回”，不要从验证集剔除来提高准确率。不发送真实敏感记忆给新供应商；使用经过许可且脱敏的数据，并保留事实关系。

建议 JSONL 字段：

```json
{"case_id":"case-001","cluster_id":"session-001","split":"calibration","language":"zh","origin":"user","pending":false,"media":false,"message":"用 Python 处理 CSV","history":[],"local_preferences":"","gold":"no_clarification","gold_evidence":["message explicitly specifies Python"],"tags":["specified"]}
```

这是格式示例，不是已标注数据。gold 可为 no_clarification、needs_preference、insufficient_evidence、ineligible。由独立人工根据原文和可见证据给标注；有分歧时复核，并报告分歧率。旧模型、Jev 和普通小模型都不是真值。

调整集只用于问题措辞、阈值、byte 上限和组合规则选择。冻结后将问题源码 hash、policy 版本和阈值写入 manifest，生成 policy_digest。验证集只能读取一次；调参后需新验证集，不能反复刷封存分数。

## 4. 第一阶段只看选择性判断是否值得继续

分别统计：总样本数、确定性不适用数、实际 Jev 请求数、模型合同有效数、would-fast-pass 数、误放行数、必要澄清遗漏、回退数以及 unknown 数。

误放行是“被快速放行但人工认为需要先问偏好”，覆盖率是全体符合原定范围请求中被放行的比例。低覆盖、高正确率也可能没有经济意义。画风险—覆盖率曲线并按语言、多意图等预设子组报告，不把 confidence 当作正确率。

不要把三个 question 的 confidence 相乘。对整个策略结果做校准和验收。评估复杂或不适合 Jev 的输入时，正确 abstention 本身是有效结果，服务故障则单列。

只有有希望在覆盖率、风险和额外费用之间取得收益，才进入端到端矩阵；阴性结果可以直接结束。

## 5. 端到端矩阵

起步可用验证集中预先选定的 30 个完整多轮会话任务，四组、两次重复，共 240 个任务 Trial。每个任务/重复形成包含四组的 Comparison Block，随机轮转组内顺序。统计独立单位是会话任务，不是每个 HTTP request，也不是两次重复。

每组使用完全相同的主模型、Provider 参数、初始 Session、Workspace、Memory、Tool catalog、预算、超时和用户答案事实。隔离状态根，禁止前一组学习到的偏好流入后一组。缓存冷热条件应平衡或清楚分层记录，不只比较有利于新组的热缓存。

模拟用户只在被问到对应信息时提供预先冻结的答案；不能偷偷给某组额外提示。必要时由盲审人工补充评估问题是否合理。不能把“立即提出一个无用问题”当作低延迟胜出。

继续使用真实 Runtime 装配、AgentTurnRunner 和实际 Tool 接口。不能只重放录制后的上下文声称完成端到端验证；gate 改变了交互分支时，后续 Session 与工具结果必须由该组真实执行得到。

## 6. 任务验收与指标

任务成功以外部文件／JSON／工具 receipt／约束清单验证；开放文本由不知道组别的人工评审。Jev 可以提供诊断，但不得同时作为优化目标和唯一成功裁判。

主要质量指标：最终任务成功率、用户约束满足率、必要澄清遗漏、多余提问、额外轮次及返工。主指标和非劣容忍度必须预先选择，不能看结果后挑“唯一改善的那个”。

费用指标：每个预定任务总费用、每个成功任务分摊费用（保留失败任务消耗）、Jev、旧分类回退、问题生成、主 Agent、Curator、重试、后置学习分别占比。不要只统计最后一次主模型调用或 UI 的 Usage。费用源是完整磁盘 CallLedger，必须验证 ledger health；内存最近记录不是完整账单。

延迟指标：请求到首个有效回复／动作的 P50/P95、完整任务的 P50/P95、分类局部延迟、用户等待时间、Jev 回退串行时间。成功组和全部固定分母分别报告。超时属于删失／失败，不能删掉后重新算“更快的 P95”；如果尾部由超时支配，报告分位数下界及超时占比。

所有 planned Trial 都要有 terminal record。失败、取消、超时、429、unknown、回退和 usage 缺失留在分母。基础设施污染需要重跑时，对称重跑整个 Comparison Block，并同时保留首次 attempt 和费用，不能只重跑 treatment 的坏样本。

推断按任务 cluster 做配对 bootstrap 或合适的配对二项检验，报告区间。30 个任务不足以可靠证明微小非劣时，应明确证据不足；不能用“差异不显著”推导两组等效。

## 7. 费用许可与执行边界

任何 live preflight 都可能收费。运行前先生成不可变 manifest、总请求数上限、总输出预算、币种和费用上限，得到明确批准。每次真实请求前预留预算；请求超时后未知收费不能释放为零。停止后的报告必须保留未核实费用／reservation。

Jev 使用独立凭据和显式数据许可；主模型沿现有 Provider。不得运行 `pico doctor --probe` 或已有 live benchmark 当作“免费准备动作”。普通 SDK 自带重试应关闭或按 plan 记为独立 attempt。

本 PR 未提供自动执行 live 实验的 CLI，因此不要编造 `pico bench jev` 等命令。Codex 应先实现 checkout-only plan/run/rebuild 入口，再在获批后执行；rebuild 必须仅读本地 immutable records，不能重新请求模型。

## 8. 启用、继续或放弃

进入验证集前冻结：允许的误放行风险、任务成功率非劣界限、最小值得维护的费用节省、首响应和完整任务 P95 预算、允许回退率、样本数和停止规则。当前没有真实流量和 SLO，本文不伪造“通用上线阈值”。

支持小范围启用：完整且可复建的计量；下游质量达到预注册非劣界限；至少一个预定用户价值指标有可信净改善；其余延迟/失败约束无不可接受退化；中文与混合语言子组没有隐藏回归；D 相对 B、C 仍有维护价值；有独立人工批准。

应放弃：没有原调用量；B 取消前置分类同样好且更简单；C 普通小模型足够好；Jev 只有局部分类改善却没有任务收益；回退吞掉节省；多意图/中文退化；无法建立供应商数据处理许可；无法可靠核账。

数据不足：保持 off，标为 inconclusive，不宣传收益。

最后交付：精确 commit/manifest、固定分母、原始 attempt 与 ledger、独立验收结果、配对统计、全部异常列表、可无模型调用重建的报告，以及 activate / remain-off / abandon 的依据。ship_complete、measurement_valid、positive_claim_eligible 分开表达。

## 9. Codex 开工指令

先阅读 `AGENTS.md`、本实施方案和本协议，核对 PR 最终 commit；先完成所有 credential-free 测试和真实使用量调查。评测适配器只存在于 checkout-only benchmark 侧，先实现 A/B/C/D 单轴变化、记录和离线重建测试；不得重写 Runtime 或激活旧 Skill Gate。

提交一个不执行付费请求的实验计划与成本上界。得到明确费用和数据许可后才运行真实模型；遇到缺失事实、统计不足或阴性结果保留并报告，不为使 Jev 看起来有效而更换分母或验证集。不得自动合并 PR、开启默认 gate、替用户审批操作或修改 sealed data。
