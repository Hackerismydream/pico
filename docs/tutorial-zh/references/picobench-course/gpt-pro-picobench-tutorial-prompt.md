# GPT Pro 任务：写一篇真正教会读者 PicoBench 的教材

你现在负责为“Pico（秋招）”课程写一篇完整教材，主题是：我们怎样设计和运行 PicoBench，以及怎样用证据判断一个 Agent 改动是否真的有效。

目标仓库：

`https://github.com/Hackerismydream/pico`

请读取包含本 Prompt 的 branch 或 commit，并以仓库相对路径访问后续材料。

先完整阅读并遵循：

`docs/tutorial-zh/references/picobench-course/writing-skill/SKILL.md`

按该 Skill 的要求读取必要参考。仓库中的课程快照用于校准读者高度和教学质量，不是供你复制的文章模板。

## 最终目标

直接交付一篇完整的中文 Markdown 教材，不要先给大纲，也不要停在方案。

目标读者是已经读过 Pico 前置课程、但还不会系统设计 Agent 评测的初级开发者。读完以后，他应该能够拿到一个新的 Agent 改动，独立设计或审查一条从“问题”到“允许做出结论”的评测证据链，并能回答：

- 为什么模型自报完成不能代表任务成功；
- baseline 和 treatment 应该怎样形成公平对照；
- Trial、Pair、Comparison Block、Verifier 和 Artifact 各自解决什么问题；
- Provider、Runtime、Delivery、任务结果和评测基础设施故障为什么不能压成一个 success；
- 为什么实验完成、测量有效和正向结论资格是三个不同判断；
- 一个看起来更好的数字，什么时候仍然不能成为项目结论。

## 你的自主权

除最终交付、事实边界、安全边界和仓库约束外，不限制你的研究方法、分析过程、源码取样、案例选择、章节结构、篇幅、配图方式或最终结论。

下面提供的文件、概念和历史线索只是调查起点，不是预设答案。你可以推翻它们、重新组织问题，或者发现更好的文章主线。若当前源码与交接材料冲突，以当前证据为准，并在交付说明中指出差异。

请自己决定：

- 这篇教材真正的语义中心；
- 用哪个真实实验贯穿全文；
- 哪些概念需要先解释，哪些可以延后；
- 是否需要图、表、代码片段或外部比较；
- 文章应在什么地方结束。

不要暴露你的内部领域模型、证据表、分析日志或写作检查表。

## 不可违反的事实与权限边界

写作前先恢复 current reality。确认当前读取的 branch、commit 和最新 `main` commit，不要假设包含本 Prompt 的分支就是 main。

如果你的环境支持 Git checkout 和命令执行，运行只读的 `git fetch origin main`、`git status`、`git rev-parse HEAD` 和 `git rev-parse origin/main`。如果只能读取 GitHub 仓库，则使用 GitHub 提供的 branch、commit 和文件信息完成核验，并把无法执行的命令标记为 `NOT_RUN`，不要伪造本地验证。

以最新 `origin/main` 作为当前稳定实现的事实来源。本分支增加的教材参考快照不会改变 Pico 产品代码。当前 checkout 如果还包含其他未进入 main 的实验，只能作为明确标注 commit、分支和 evidence 身份的受控案例，不能写成已发布能力。

必须守住以下边界：

- PicoBench 是 checkout-only evaluation harness，不是公开的 `pico bench` 产品命令；
- `pico/eval_engine/` 是独立的 Runtime Hook 和 LLM Judge scaffold，不能与 PicoBench 混用；
- Evolver 的候选筛选、sealed evaluation 和 activation 属于另一条链路；
- 模型回答、Call Record、Turn terminal、Delivery outcome 和 task verification 是不同证据；
- `ship_complete`、`measurement_valid`、`positive_claim_eligible` 必须分别解释；
- controlled benchmark 不能写成生产 SLA、全局能力提升或个人生产贡献；
- 所有数字都必须绑定具体 commit、workload、baseline、treatment、Trial 或 Pair 分母、Verifier、统计口径和 eligibility；
- 不得运行任何付费评测，不得设置 paid execution 开关，不得修改代码，不得 commit、push、创建 PR，也不得写入或覆盖飞书页面。

## 课程参考材料

GPT Pro 不需要访问飞书。所需课程材料已经以只读 Markdown 快照保存在：

`docs/tutorial-zh/references/picobench-course/`

先阅读：

- `README.md`：快照范围、课程目录和使用边界；
- `learning-method.md`：这套课程希望读者怎样学习项目。

再从以下代表文章中自主选择真正有助于本章的材料：

- `p00-agent-harness.md`：怎样从一条真实请求建立普通语言模型；
- `p05-session-and-recovery.md`：怎样从失败、所有权和事实边界推导机制；
- `p09-call-efficiency.md`：怎样把测量、优化和证据边界连在一起。

`agent-evaluation-placeholder.md` 只证明目标页目前没有正文，不是内容来源。

现有课程最重要的共同点是：从可见问题进入，先建立普通语言模型，再让源码和测试证明设计。请继承这个质量标准，不要复制标题、节数、固定节奏或句式。

这些文件是飞书内容快照，不是当前源码事实。涉及 Pico 行为、测试或指标时，必须重新检查当前仓库。

## 源码与证据入口

以下是起点，不是穷举清单：

- `benchmarks/README.md`
- `docs/evaluation/README.md`
- `benchmarks/picobench/README.md`
- `benchmarks/picobench/suites/`
- `benchmarks/picobench/plan.py`
- `benchmarks/picobench/harness.py`
- `benchmarks/picobench/host.py`
- `benchmarks/picobench/verifier.py`
- `benchmarks/picobench/records.py`
- `benchmarks/picobench/reducer.py`
- `benchmarks/picobench/claims.py`
- `benchmarks/picobench/artifacts.py`
- `benchmarks/picobench/report.py`
- `benchmarks/picobench/campaign.py`
- `Makefile`
- 与你最终选择案例对应的 Pack、Task、Verifier、测试和本地 evidence

你应独立恢复 PicoBench 的真实执行链，而不是照着文件顺序写文章。至少需要查清：实验身份怎样冻结，单变量 Pair 怎样形成，Trial 是否真的经过 Pico Runtime，Verifier 怎样与 Agent workspace 分离，污染为何触发整组处理，失败怎样保留，报告怎样从不可变记录离线重建，以及结论资格由谁裁决。

选择一个最能承载文章主线的当前或历史实验作为贯穿案例。不要因为交接材料提到 Scheduler、Tool Disclosure、CallEfficiency、Myna 或 Ability Transfer 就强行选它们。先比较它们的教学价值和证据完整性，再决定使用哪一个。不要拼接不同 experiment 的数字。

如果外部资料能够揭示一个真正影响设计的共同问题，可以查阅直接源码、论文或官方资料。若不能改善读者的判断能力，就省略行业比较。

## 写作质量

正文必须是一篇教材，不是源码巡礼、评测白皮书、审计报告或简历指标集合。

从一个真实问题、失败或反直觉结果进入。先让读者看到正常实验如何从问题走到结论，再把污染、重试、失败和拒绝结论放回对应机制。术语在需要使用时再引入。代码片段应告诉读者现在看哪些字段，以及这些字段证明了什么。

不要用“学习目标”“读前准备”“本文分为”开场。不要堆砌边界声明、测试数量和历史数字。不要为了整齐复制其他章节的结构，也不要为了显得完整覆盖每个 PicoBench 子系统。

完成初稿后，按教材 Skill 分别做事实、读者、语义和证据审查，再修订成最终稿。若图能显著降低理解成本，并且你的环境提供图像生成能力，可以制作配图；否则给出可以直接执行的图片 brief。图必须服务附近的问题，不能成为装饰。

## 验证与交付

如果环境支持命令执行，在不产生外部费用的前提下运行当前 checkout 的 `make picobench-smoke`，并根据正文实际引用的机制选择相应的 `uv run pytest ...` 验证。不要为了扩大数字运行与正文无关的测试。

如果环境只能读取 GitHub，仍然完成教材，但必须把运行时验证标为 `NOT_RUN`。可以引用当前源码、测试内容和 commit-bound historical evidence，却不能把“测试代码存在”写成“测试已经通过”。

最终只交付：

1. 完整教材 Markdown；
2. 一段简短核验记录，说明：
   - 最终采用的标题与课程位置建议；
   - 检查的稳定源码 commit；
   - 使用的实验 artifact 和其证据身份；
   - 实际运行的命令与结果；
   - 仍不能做出的结论；
   - 若使用配图，说明每张图解决的理解问题。

不要向我展示中间提纲，也不要等待我替你选择结构或案例。只有出现会改变任务范围、技术事实或外部权限的真实歧义时才提问。
