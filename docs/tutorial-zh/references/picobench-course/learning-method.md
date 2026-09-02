<!--
Source: https://icnoljnkix43.feishu.cn/wiki/Ks6uw914Cir7jTkg4gTcPa1Tnmg
Node token: Ks6uw914Cir7jTkg4gTcPa1Tnmg
Document ID: XwM5dnBEyoJy8txuYilcKMNQn7f
Revision: 1
Fetched: 2026-09-02T09:12:58.827Z
Snapshot purpose: read-only source material for the PicoBench tutorial prompt.
Feishu-hosted images are intentionally omitted from Git; their alt text is retained.
-->
# 学习方式

# 从整体到局部学习

> 很多时候项目代码很多，不可能完全读完，pico正式版本是这样，哪怕是你去工作了也一样，很可能你这个项目接手一年了，你也才读了50%的代码（也很不错了），我们更多的是需要知道出现需求/出现问题里，对应的链路该去哪里找

所以对于Agent项目，比较推荐以这样的方式来从整体到局部的学习：

对于这个问题

> 用户给 Agent 一个任务以后，到最终得到结果，中间到底发生了什么？

先尝试用十句话以内把故事讲出来：

```Plain Text
用户输入
→ 创建 / 恢复 Session
→ 构造 Context
→ 调用 Model
→ Model 决定回复或 Tool Call
→ Runtime 执行 Tool
→ Tool Result 回到 Context
→ 再次调用 Model
→ 判断是否继续
→ 输出结果并持久化状态
```

这十步都还没搞清楚之前，我甚至不建议深入 Memory、Tracing、Subagent、Evaluation等这些复杂的模块

因为这些东西都是附着在主条执行链上的。

所以第一原则是：**先理解 Runtime 的因果链，再理解项目的代码结构。用这样从整体到局部的学习方式**

# 纵向切片学习（第一次看项目的时候，用一条请求去看整个项目）

Agent项目不像其他后端项目有复杂的领域建模，繁多的用户入口。它暴露给用户的就是一个请求界面（TUI / GUI / IM），所以如果你是第一次学习pico，那你应该选一个最简单的任务，比如：

```Plain Text
用户：帮我读取 README，然后总结项目。
```

然后追踪它：

```Plain Text
入口在哪里？
    ↓
谁创建 Agent / Runtime？
    ↓
用户消息存在哪里？
    ↓
Prompt / Context 在哪里组装？
    ↓
Model API 在哪里被调用？
    ↓
Tool schema 怎么传给模型？
    ↓
Tool call 怎么解析？
    ↓
Tool 怎么执行？
    ↓
结果怎么塞回 conversation？
    ↓
什么条件结束 loop？
    ↓
最终结果怎么返回？
```

第一次读项目，我认为只需要读这一条链路。

这实际上是在做一种：**Vertical Slice Learning（纵向切片学习）**

一个错误的做法是

```Plain Text
先把 provider 全读完
再把 memory 全读完
再把 tools 全读完
再把 context 全读完
```

这样很容易陷入到局部细节

# 阅读代码时，不问“这个函数干什么”，而问“为什么需要它”

比如看到：

```Plain Text
compact_context()
```

初学者会研究：

> 这个函数具体怎么实现？

但更应该先问：

> Runtime 为什么会调用它？

然后继续：

```Plain Text
什么条件触发 compact？
↓
如果不 compact 会发生什么？
↓
compact 前后保留什么？
↓
哪些信息不能丢？
↓
compact 之后 Agent 如何继续任务？
```

这时候你理解的就不是函数，而是**Context Management 这个工程问题**

这样的话可以形成一个阅读公式：

> **代码结构 → 运行时问题 → 设计决策 → 实现机制**

而不是只停留在：

> **函数 → 函数 → 函数 → 函数**

# 建立通用的问题树

建立通用的问题树，遇到同场景下的问题可以迁移（这种刻意训练对场景题尤为重要）

```Plain Text
Agent 如何完成一个任务？
│
├── 如何决定下一步？
│   └── Agent Loop
│
├── 模型知道什么？
│   ├── Context
│   ├── Prompt
│   └── Memory
│
├── Agent 如何作用于外部世界？
│   ├── Tools
│   └── MCP
│
├── 长任务如何持续？
│   ├── Session
│   ├── Checkpoint
│   └── Resume
│
├── 出错怎么办？
│   ├── Retry
│   ├── Timeout
│   └── Failure isolation
│
└── 怎么知道 Agent 做得怎么样？
    ├── Trace
    ├── Evaluation
    └── Metrics
```

# 面向面试的费曼学习法

面试的核心：**你是否理解问题、是否理解设计、是否能解释 trade-off。**

我们看项目的目标：

**第一目标：能在面试里讲清楚、扛住追问**
**第二目标：真正学到可迁移的 Agent 知识**

所以我们在看项目的时候需要有一些调整，学习的最小单位不再是“模块”，而是“一个可面试的技术问题”

核心循环是：

**读懂一条链路 → 压缩成自己的解释 → 模拟追问 → 暴露知识缺口 → 回源码补洞 → 再讲一次**

比如不要学习：

> Context 模块

而是学习：

> 为什么 Agent 需要 Context Management？这个项目是怎么解决上下文持续膨胀的？

不要学习：

> Memory 模块

而是：

> Agent 为什么需要长期记忆？Memory 和 Context 有什么区别？这个项目什么时候写、什么时候读？

这样一开始，学习方向就已经跟面试对齐了。

## 每学一个东西，都强迫自己产出一个“六问答案”

我认为这是最重要的方法。

例如你学习一个 Agent 项目的 Context Compression。

不要以“我把代码看懂了”为完成标准。

而是要求自己脱离代码回答六个问题：

```Plain Text
1. Problem：为什么需要它？
2. Baseline：最简单的方案是什么？
3. Design：这个项目怎么做？
4. Mechanism：运行时到底怎么工作的？
5. Trade-off：为什么这样设计？代价是什么？
6. Evidence：你怎么证明它有效？
```

这六个问题其实对应了面试官最常见的追问方式。

比如 Context：

第一层：

> 为什么要做 Context Compression？

你应该能回答：

> Agent 在长任务中会不断累积用户消息、模型输出和 Tool Result，如果全部放进 Context，一方面会触碰 Context Window，另一方面也会增加推理成本，同时大量历史信息可能干扰当前决策。所以 Runtime 需要在保留任务状态和关键证据的前提下压缩历史上下文。

然后面试官继续：

> 那最简单的方案是什么？

你说：

> 最简单就是超过 token threshold 后直接 summarize 历史消息。

继续：

> 那有什么问题？

你说：

> 单纯 summary 容易丢失文件路径、tool execution result、未完成事项这类未来执行仍然依赖的信息，所以不能简单把所有历史都等价压缩。

到这里，真正的 Agent 知识就出来了。

这才是费曼学习。
