# PicoBench 教材飞书参考快照

> 来源知识库：Pico（秋招）
> 根节点：https://icnoljnkix43.feishu.cn/wiki/UYFtwZL8Hip1hIk8oP1cIYVNngb
> 空间 ID：7647853868948229086
> 目录抓取时间：2026-09-02T09:14:17.672Z

这个目录保存 GPT Pro 编写 PicoBench 教材所需的飞书文本快照。它只用于校准读者高度、教学方式和既有课程语气，不是 Pico 当前实现的技术事实源。

技术事实仍以最新 `origin/main`、当前测试和 commit-bound evaluation evidence 为准。飞书原图未纳入 Git，正文只保留配图说明，避免提交会过期的飞书授权链接和报告资产。

## 已保存全文

- [可直接交给 GPT Pro 的 PicoBench 教材 Prompt](gpt-pro-picobench-tutorial-prompt.md)
- [学习方式](learning-method.md)
- [P00：什么是 Agent Harness](p00-agent-harness.md)
- [P05：Session 与恢复](p05-session-and-recovery.md)
- [P09：CallEfficiency](p09-call-efficiency.md)
- [Agent 评测占位页](agent-evaluation-placeholder.md)
- [教材写作 Skill 快照](writing-skill/SKILL.md)

这些页面是当前 GPT Pro Prompt 实际引用的代表材料。没有把整套课程全文复制进仓库；需要扩展快照时，应重新读取对应飞书 revision，并保留来源和抓取时间。

## 知识库目录快照

- 学习方式
- 简历描述（初版，将会继续迭代）
- 项目地址 & 怎么部署
- P00｜什么是 Agent Harness：从一条飞书消息认识 Pico
- P02｜Scheduler：让请求获得顺序、容量与去向
- P01｜Agent Host：三个入口如何运行同一种 Agent
- P03｜Agent Loop：模型为什么要边做边看
- P04｜上下文工程：Pico 怎样准备并维护模型的工作现场
- P05｜Session 与恢复
- P06｜Memory：过去的经历怎样安全地影响下一次任务
- P07｜Tools System：模型意图如何变成受控行动
- P08｜Agent Gateway：外部事件如何进入 Runtime，Agent 结果如何回到原渠道
- P09｜减少 Agent 成本的实践：Pico 如何用 CallEfficiency 先算清，再优化
- 待更新章节（含子节点）
  - 怎么把Pico包装成自己的项目
  - 面试逐字话术稿
  - Agent评测 & 简历指标实验
  - 自进化

## 使用规则

1. 先读 `learning-method.md`，恢复课程的学习目标和读者模型。
2. 从 P00、P05、P09 中自主选择真正有助于 PicoBench 章节的写作判断，不复制标题、节数和句式。
3. `agent-evaluation-placeholder.md` 只证明目标页目前是占位页，不提供技术内容。
4. 任何源码、行为、数字或证据结论都必须回到当前仓库核验。
5. 本快照不是飞书发布副本，不应反向覆盖线上页面。
6. GPT Pro 应从 `gpt-pro-picobench-tutorial-prompt.md` 开始；该 Prompt 的所有必需写作材料都已改为仓库相对路径。
