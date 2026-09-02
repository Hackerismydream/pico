# Pico + Myna Evidence-Driven Evolution Result

Status: completed controlled evaluation on 2026-08-31.

## User-visible story

A user completes an ordinary Pico task. Pico records the Turn result, Tool
receipts, file changes, verification commands, and delivery outcome. Myna
stores that evidence as repository-scoped Task Experiences. When three
independent verified Experiences describe the same Ability, Myna compiles a
versioned instruction-only Ability Card from the exact bound Source Facts.

The candidate is created automatically, but production authority is not. A
candidate remains pending until its evidence and activation receipt satisfy
the configured policy. On a later task, Myna Recall returns relevant active
candidates, Pico combines them with its other Skill sources, and a fail-closed
LLM Gate may select an exact revision for Context injection. Unknown IDs,
Provider failures, malformed Gate output, and missing trigger conditions
abstain. The next independent task verifier, rather than the model's own text,
determines whether the learned Ability helped.

```text
ordinary Pico task
  -> evidence-backed Task Experience in Myna
  -> repeated verified Ability group
  -> Source-Fact-preserving Ability Card revision
  -> evidence and human/evaluation activation receipt
  -> Myna Recall
  -> Pico exact-ID LLM Gate
  -> later task and independent verifier
```

## Controlled experiment

The suite contains six Pico repository Abilities, 18 learning instances, 24
identity-disjoint held-out implementation tasks, and 24 confusing negative
queries. Model, task prompt, fixture, tools, execution limits, and verifier are
held constant inside every pair.

Stage A isolates learned content by routing the exact automatically compiled
Myna Ability Card to its known Ability. Across 48 paired held-out evaluations,
NoSkill passed 15 and the Myna Skill arm passed 26: a +22.92 percentage-point
delta with a task-clustered 95 percent interval of [+8.33, +39.58]. All 96
trials were measurable and the offline verifier passed.

Stage B evaluates the automatic Recall and Pico Gate path. Across another 48
paired evaluations, Control passed 15 and automatic Recall + Gate passed 24: a
+18.75 percentage-point delta with a task-clustered 95 percent interval of
[+6.25, +33.33]. All 48 pairs were valid, there were zero treatment
regressions, and the Gate injected an exact revision in 40 of 48 treatment
trials. The offline verifier reconstructed the manifest, candidate snapshots,
raw outcomes, aggregate, claim, inventory, and complete CNY 1.6420908 Provider
ledger.

The confusing-negative check found eight Recall candidates. The Gate rejected
six and selected two adjacent-but-out-of-scope candidates. Therefore the
task-effect measurement is valid and statistically positive, while automatic
production activation remains disabled pending a stricter trigger Gate. This
separates demonstrated learning value from deployment authority.

## 中文简历表述

设计并实现 Pico + Myna 证据驱动的自进化链路：将普通任务中通过验证的执行轨迹自动沉淀为仓库级、
可版本化的 Ability Card，并通过 Recall 与 fail-closed 的精确 ID LLM Gate 在后续任务按需注入；
构建覆盖 6 类真实仓库策略、24 个隔离测试任务的成对 A/B，端到端通过率由 31.25%（15/48）提升至
50.00%（24/48），提升 18.75 个百分点，任务聚类 95% 置信区间为 [+6.25, +33.33]，且无成对回归。

## 面试口述

我解决的问题是：Agent 虽然能完成一次任务，但遇到同类仓库问题时仍会从零开始。我的方案把自进化拆成
两个职责清晰的系统：Pico 负责记录工具调用、文件修改、验证命令和最终交付结果；Myna 负责把同一仓库中
多次成功且经过验证的经验聚合成带版本的 Ability Card。生成 Skill 时不是只读一段摘要，而是读取经验绑定
的原始 Source Facts，因此会保留决策表、允许和拒绝的输入以及失败边界。下一次任务中，Myna 先召回候选，
Pico 再用 fail-closed Gate 检查触发条件、可用工具和精确 revision，匹配后才注入上下文。

为了证明提升不是随机 Prompt 效果，我固定了 18 个学习样本和 24 个互不重叠的测试任务，覆盖 6 类真实
Pico 策略；每个 A/B Pair 使用相同模型、任务、工具、调用上限和独立 verifier，唯一变量是是否启用自动
Recall + Gate。最终 Control 通过 15/48，Treatment 通过 24/48，提升 18.75 个百分点，95% 置信区间
下界为 +6.25 个百分点，且没有成对回归。我还加入 24 个混淆负例；其中仍有 2 次错误选择，所以系统可以
自动生成和推荐新能力，但生产激活继续要求证据和人工授权。

## Evidence identity

- Pico commit: `e8eeea261c65d2e69d3f8977fecdb40c09891ae9`
- Myna commit: `8d513e3ff8ef62ef9c90fba1d0626b18e402d07f`
- Stage A approval digest:
  `6592ddcc8227b74fff75e32f379de02d62e377e9cf7272404e6582ea06f823ab`
- Stage B approval digest:
  `1869e0a4aa50562aefb98257a32a760481d10163c1c5042a657e54a576ca94e8`
- Stage A local evidence:
  `.pico/evidence/pico-ability-transfer/stage-a-v4-formal`
- Stage B local evidence:
  `.pico/evidence/pico-ability-transfer/stage-b-gate-v7-formal`
