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

当前必须诚实说：机制的 exact-wheel E2E 已通过；formal runner 的无费用 preflight 也已用相同 wheels 生成并激活 6 个候选、绑定 18 条学习映射和 12 份 Control/Treatment snapshot，并在 24 个 hard negative 上保持零错误召回。正式 96-Trial 付费实验只冻结了协议、候选 wheel、预算和 approval digest，尚未执行。因此现在能说“闭环真实工作且安全门有效”，不能说“任务成功率已经提升 X%”。

## 面试官问“自进化是怎么做的”时，90 秒回答

> 我们没有做模型权重自训练，而是做 verified Skill evolution。用户正常完成一个 Pico Turn 后，Pico 先把轨迹写入 Myna，再上报一份系统拥有的 Turn Evidence，里面是工具调用、真实 exit code、文件变化、交付状态和实际注入的 Skill revision。Myna 只把同仓库、三个不同 Episode、并且有系统成功 Verification 的 Task Experience 放进同一能力组。LLM 只能生成六类 instruction 文本，Skill 的成员关系、身份、provenance 和生命周期全部由系统计算，生成后先是 draft。当前版本需要 operator 或 formal-evaluation receipt 才能激活；下一次相似任务，Myna 从 agent track 只召回当前 active revision，Pico 再和本地 Skill 融合后注入 Context。新经验会生成 successor，发现回退可以 reject 或追加 head 做 rollback，历史不覆盖。我们用 exact-wheel E2E 验证了 draft、激活、注入、hard negative、Supersession、rollback、reject 和重启恢复；任务效果则用 instance-disjoint A/B 单独测，Control 和 Treatment 唯一差别是 exact Skill 是否 active。正式 A/B 尚未付费执行，所以我不会提前报提升数字。

## 常见追问

### 为什么三次？

三次不是统计学上证明能力的魔法数字，而是第一版候选生成阈值：一次容易把偶然解法固化，两次仍难区分巧合，三个不同 Episode 才允许生成 draft。它只决定“可以候选”，不决定“可以上线”；真正的正向效果仍由 held-out A/B 决定。

### 为什么不自动激活？这还算自动进化吗？

Capture、证据绑定、资格判断、聚类和 draft 派生是自动的；激活目前受 receipt gate 控制。我们把“自动学习”和“自动获得运行权”拆开，因为后者会直接影响后续用户任务。只有 `skill_transfer_v1` 对精确候选给出 eligible positive result 后，才有理由讨论自动 activation policy。

### 怎么防止学到 prompt injection？

历史消息和工具文本都是 untrusted evidence input。Provider 只看到有界投影，不能指定 identity、引用、工具、脚本或配置；返回值走 closed Schema。即使恶意文本诱导它返回脚本，未知字段或 executable content 也会被拒绝，原始 Experience 仍保留但 Skill 不生效。

### 怎么证明 Skill 真被用了？

`injected_skill_ids` 只能证明 Context 暴露，不能证明任务改善。Task effect 必须看独立 verifier；实验还要求 Treatment 注入 exact revision、Control 零注入、Pair workspace digest 一致，并从 raw Trial 重新计算 aggregate 和 claim eligibility。
