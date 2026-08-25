# Verified Skill Evolution：面试故事与证据边界

## 一句话定位

我们做的不是让模型偷偷改权重或让 Agent 自己改代码，而是把普通任务中已经被系统验证过的成功经验，编译成可追溯、可拒绝、可回滚的 instruction-only Skill；下一次相似任务再把已激活的 Skill 作为上下文注入。

## 用户使用路径：一次正常任务怎样变成下一次能力

用户只是在 Pico 里完成普通任务。Pico 正常调用工具、运行检查并交付结果；用户不需要写 benchmark YAML，也不需要点击“学习”。Turn 结束后，链路是：

```text
普通 Pico Turn
  -> Pico 先把消息写入 Myna
  -> Pico 上报系统拥有的 Turn Evidence
  -> Myna 将 Evidence 绑定到 Task Experience
  -> 同一能力累计 3 个不同 Episode 的 verified success
  -> 进入 durable derivation queue
  -> Semantic Provider 只生成受限的 Skill 内容字段
  -> Myna 编译为不可变 SKILL.md + manifest，状态为 draft
  -> operator 或 formal evaluation 带 receipt 激活
  -> 下一次任务同时做 user-track Memory Recall 与 agent-track Skill Recall
  -> Pico 将 Myna Skill 与本地 Skill 一起融合、选择并注入 Context
  -> 新 Turn 的 Evidence 再记录实际注入了哪个 revision
```

用户无感的是 Capture、Evidence 绑定、资格判断和 draft 派生；当前版本没有开放“未经评估自动激活”。这是刻意的安全边界，不应在面试里说成完全自治上线。

## 为什么它不是“LLM 看三段日志随便总结”

系统把模型能决定和不能决定的内容分开了。

模型只能提出 `name`、`description`、`applicability`、`procedure`、`verification` 和 `failure_avoidance` 六类 instruction 文本。仓库命名空间、三条 Experience 的成员关系、验证是否成功、Fact 与 Evidence 引用、`skill_id`、`revision_id`、前驱 revision 和生命周期都由系统计算。脚本、二进制资产、工具注册、配置修改和 Runtime patch 会被 Schema 拒绝。

资格门也不是“出现三次就学”：必须是同仓库、三个不同 Episode、Task outcome 为 success，并且至少有一个系统来源的成功 Verification。模型说“测试通过”不算；Pico 记录的命令和 exit code 才算。失败的 Provider 不影响已经落盘的 Experience，只留下可恢复的 derivation job。

## 安全闭环

Skill revision 不原地覆盖。每次派生得到新的 content-addressed revision：

- `draft -> active` 需要 operator 或 formal-evaluation receipt；
- 新 revision 激活时，旧 revision 进入 Supersession；
- reject 追加生命周期记录，不删历史；
- rollback 追加一个指向历史 revision 的新 active-head record；
- Recall 只返回当前仓库、当前 head、相关性大于零且未 rejected 的 Skill；
- 任一 Skill source 故障由 SkillForge 隔离，本地 Skill 仍可继续工作。

所以“进化”是可审计的知识制品演进，不是不可逆的模型突变。

## 实验怎样证明不是乱做

实验只改变一件事：derived Skill 是否 active。Control 和 Treatment 都保留相同的 Myna Capture 和三条 verified learning Experiences；Treatment 额外激活精确 revision，Control 保持 draft 不可用。

`skill_transfer_v1` 冻结 6 个能力族，每族 3 个学习实例、4 个 held-out 和 4 个 hard negative。学习集共 18 个实例；24 个 held-out 在两臂各跑两次，得到 48 对、96 个主 Trial；另有 24 个 hard negative。学习、held-out 和 negative 的 identity 全局不重叠。

候选生成子进程只接收 learning projection，不会收到 held-out prompt、fixture 或 hard negative；三份 split 各自有冻结 digest。candidate receipt 还逐条绑定 `learning_instance_id -> experience_id`，并对 Control/Treatment runtime snapshot 做目录 digest。

正向结论必须同时满足 48/48 Pair 有效、24/24 negative 零错误注入、revision 的三条 Experience provenance 完整、独立 verifier 全部可重建、零 Treatment regression，并且按 held-out task 聚类的 95% bootstrap CI 下界大于 0。所有 raw、budget、candidate 和派生报告还会进入带 SHA-256 的 `inventory.json`。Provider 或基础设施故障会使 Pair 无效，不能被记成低分来制造差异。

正式实验已经完成，而且结果不是“Skill 一注入就变强”。96 个主 Trial 构成 48 对有效比较，基础设施失败为 0；Control 通过 32/48，Treatment 通过 25/48，差值为 -14.58 个百分点，按 24 个 held-out task 聚类的 95% bootstrap 区间为 [-31.25, 0]。Treatment 有 3 对收益、10 对回退；24 个 hard negative 全部完成且错误注入为 0。离线 verifier 能从 raw outcomes 重建 aggregate、claim、预算账本、候选快照和 SHA-256 inventory。

这证明了两件不同的事：第一，自动 Capture、verified Experience、Skill 提炼、Recall 和精确 revision 注入的链路真实可运行；第二，当前“相关就注入”的策略会产生负迁移，因此不能开放自动激活，也不能在简历里写成功率提升。实验不是给功能贴金，而是替产品挡住了一个会伤害用户的上线策略。

## 面试官问“自进化是怎么做的”时，90 秒回答

> 我们没有让模型偷偷改权重，而是把用户任务里被真实检查验证过的成功经验，自动提炼成一份可追溯的操作指南。用户照常使用 Pico；Turn 结束后，Pico 把消息和真实工具结果写给 Myna。只有同一仓库里三个不同任务都成功、并且有系统记录的成功检查，才会生成 draft Skill。LLM 只能写操作步骤，Skill 来自哪些经验、当前哪个版本生效、谁批准、怎么回滚都由系统记录。下一次相似任务，Myna 召回当前 active revision，Pico 把它注入上下文，同时在新 Turn 里记录到底用了哪个版本。我们还做了 96 个真实 Agent Trial 的配对实验：同题、同模型、同工具，唯一差别是是否注入 Skill。链路和安全性都通过了，24 个无关任务零误注入；但任务通过率从 32/48 降到 25/48，下降 14.58 个百分点。因此我没有开放自动激活，反而用实验发现“会自动学”不等于“学了会更强”，下一步要解决的是技能选择和负迁移。这是我认为自进化系统最重要的工程边界。

## 简历写法

推荐写成结果完整、但不虚构正向提升的一条：

> 设计并实现 Pico × Myna 的可审计 Skill 学习闭环：从普通 Agent Turn 自动沉淀经真实检查验证的经验，生成带版本、来源和回滚能力的操作指南，并在后续相似任务中按 revision 召回；构建 96-Trial 配对评测与离线证据链，验证 48/48 Pair 可比、24/24 无关查询零误注入，并发现未加选择门的技能注入使通过率由 32/48 降至 25/48，据此阻断自动激活、将负迁移纳入上线门禁。

更短的一页简历版本：

> 搭建可审计的 Agent 自动学习闭环与 96-Trial 配对评测，支持经验提炼、版本化 Skill 召回及回滚；实验发现直接注入导致 -14.58pp 负迁移，基于 24/24 hard negative 与离线复算证据阻断自动激活，避免未经验证的“自进化”影响用户任务。

## 常见追问

### 为什么三次？

三次不是统计学上证明能力的魔法数字，而是第一版候选生成阈值：一次容易把偶然解法固化，两次仍难区分巧合，三个不同 Episode 才允许生成 draft。它只决定“可以候选”，不决定“可以上线”；真正的正向效果仍由 held-out A/B 决定。

### 为什么不自动激活？这还算自动进化吗？

Capture、证据绑定、资格判断、聚类和 draft 派生是自动的；激活目前受 receipt gate 控制。我们把“自动学习”和“自动获得运行权”拆开，因为后者会直接影响后续用户任务。只有 `skill_transfer_v1` 对精确候选给出 eligible positive result 后，才有理由讨论自动 activation policy。

### 怎么防止学到 prompt injection？

历史消息和工具文本都是 untrusted evidence input。Provider 只看到有界投影，不能指定 identity、引用、工具、脚本或配置；返回值走 closed Schema。即使恶意文本诱导它返回脚本，未知字段或 executable content 也会被拒绝，原始 Experience 仍保留但 Skill 不生效。

### 怎么证明 Skill 真被用了？

`injected_skill_ids` 只能证明 Context 暴露，不能证明任务改善。Task effect 必须看独立 verifier；实验还要求 Treatment 注入 exact revision、Control 零注入、Pair workspace digest 一致，并从 raw Trial 重新计算 aggregate 和 claim eligibility。
