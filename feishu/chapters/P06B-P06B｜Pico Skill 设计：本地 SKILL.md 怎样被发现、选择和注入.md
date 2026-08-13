# P06B｜Pico Skill 设计：本地 SKILL.md 怎样被发现、选择和注入

<callout emoji="💡">
**这一篇只讲 Pico 的 Local Skill。**Skill 是维护者写在 `SKILL.md` 里的操作说明。Pico 负责发现文件、建立本地索引、判断放完整正文还是紧凑引用，再把结果交给模型。它不会在一轮任务结束后自动把经验写成新 Skill。
</callout>

> 小林说：“按 agent-tutorial-diagrams 的规范画一张 Runtime 图。”这一次不需要回忆他的个人偏好，重点是 Pico 怎样找到同名 Skill，并让模型在动手前读到正确的步骤、资源路径和验收规则。

本章对应 `origin/main@b09bf795c73cfe57c9685060c8e5bde3f6db0207`。当前 Runtime 的路由器只装配一个 Local source；代码保留多 source、over-fetch 与 Weighted RRF 能力，主要用于确定性评测和第三方调用，不能写成当前在线路径已经接入远程 Skill 来源。

---

## Skill 在 Pico 里解决什么问题

<grid>
<column width-ratio="0.500000">
**Skill 提供方法**
告诉模型这类任务怎样做、要读哪些参考、按什么标准验收。
</column>
<column width-ratio="0.500000">
**Tool 提供动作**
真正读文件、运行命令、访问 MCP 或调用外部服务。
</column>
</grid>

模型可以先读 Skill，再决定调用哪些 Tool。Skill 本身不执行命令，也不拥有工具权限。它进入的是 Prompt，Tool 进入的是可调用 schema 与执行注册表。

| 对象 | 内容 | 本轮结束后 |
|-|-|-|
| Skill | 稳定的操作说明与配套 references/scripts/assets | 继续由本地文件管理 |
| Memory | 以后可能再次有用的用户或任务资料 | Backend 可以从当轮消息抽取与持久化 |
| Tool | 可执行能力、参数与安全边界 | 产生结果与副作用，记录进 Session/Trace |

---

## 代码地图：从磁盘文件走到模型输入

| 顺序 | 文件与符号 | 这一处负责什么 |
|-|-|-|
| 1 | `pico/memory_engine/skill_local/registry.py` | 扫描 SKILL.md、解析 frontmatter、保留来源与路径 |
| 2 | `pico/memory_engine/skill_forge/catalog.py` | 拥有 Registry、LocalPool 与文件 Watcher |
| 3 | `pico/memory_engine/skill_local/local_pool.py` | 对本地 Skill 建立 CJK-aware BM25 索引 |
| 4 | `pico/memory_engine/skill_forge/local_source.py` | 把本地命中变成带来源的 RouterHit |
| 5 | `pico/memory_engine/skill_forge/resolver.py` | 判断 activated、reference 或 abstain |
| 6 | `pico/context_engine/segments/skills.py` | 渲染完整正文、引用与 diagnostics |
| 7 | `pico/agent/tools/skill.py` | 让模型按名称调用 skill_read 读取引用正文 |
| 8 | `pico/context_engine/factory.py::_build_router` | 确认当前 Host 只装配 Local source |

## 第一步：把多个本地目录整理成一个可检索池

`SkillRegistry` 会读取三类本地来源：

- `<workspace>/skills/`：当前项目或工作区自己的 Skill；
- `skill_forge.local_dirs`：配置挂载的个人或团队目录；
- `pico/memory_engine/skills/`：随安装包提供的 builtin Skill。

Registry 的稳定身份是 `(source, name)`。不同来源里同名的 Skill 可以同时保留，旧调用方只给 name 时才需要使用优先级索引。每条 metadata 还带路径、描述、always 标记和可用性要求。

`LocalPool` 在启动时就建立 BM25 索引。索引文本把名称和描述重复加权，再拼接最多一段正文；这样用户明确说“pdf”“weather”或 Skill 名称时，短而强的信号不会被长正文淹没。整个检索过程不加载 embedding 模型，也不调用 Provider。

**图 P06B-A｜本地 Skill 从文件到可检索索引**

先看上半部分的三个来源怎样汇入 Registry，再看下半部分：workspace 中的 `SKILL.md` 变化怎样让对应 source 失效并重建 BM25。

![](images/P06B/img1.jpg)

Watcher 只监视 workspace skills。builtin 与配置目录没有被递归监视，避免对大型只读镜像建立过多系统 watcher；它们需要显式失效或由进程重新装配。

## Always Skills 与按请求检索走两条入口

标记为 `always: true` 且依赖满足的 Skill，会进入 `# Active Skills`，受 `always_max` 限制。`LocalPool.search()` 会过滤这些条目，避免同一正文同时出现在 Active 与 Routed 两个 Segment。

其余 Skill 才进入按请求检索。当前 query 包含 `agent-tutorial-diagrams`，BM25 会给同名 Skill 很强的分数；`LocalSkillSource` 再向 Registry 取出正文与路径，构造：

```python
RouterHit(
    qualified_id="local/agent-tutorial-diagrams",
    name="agent-tutorial-diagrams",
    content="<SKILL.md 正文>",
    score=...,
    meta={
        "physical_source": "workspace",
        "skill_dir": "...",
        "description": "...",
    },
)
```

如果文件在 BM25 打分后、Registry 取正文前刚好被删除，Local source 会跳过这条候选。它承诺的是“最多 k 条完整候选”，不会为了凑数发出一条没有正文的 Skill。

---

## 第二步：决定全文注入、只给引用，还是不采用

`LocalSkillResolver` 不调用大模型。它在候选集合上做三种决定：

| 结果 | 触发条件 | 模型看到什么 |
|-|-|-|
| activated | query 明确命中名称或关键词，且未超过 activation limit | 完整 Skill 正文与绝对化后的本地引用 |
| reference | 内容相关但不必全量注入，或明确候选超过全文上限 | 名称、描述以及使用 skill_read 的提示 |
| abstain | 相关性不足 | 不进入 Context |

这三个结果互斥。`activation_limit` 控制完整正文数量，避免几个大 Skill 一次占满窗口。被列为 reference 的 Skill 仍然可用：模型确认需要后调用 `skill_read(name=...)`，再取得正文。

**图 P06B-B｜候选 Skill 的准入决策**

沿主线读到 Resolver 后分三路。绿色和橙色会进入 Skills Segment；灰色 abstain 在原地终止，不会进入 Context。

![](images/P06B/img2.jpg)

`SkillsSegmentBuilder` 会把 activated 正文中的 `{baseDir}`、references、scripts、assets 和 examples 链接解析成可执行的绝对路径。不存在的目标不会被伪装成有效路径，代码块里的示例也不会被改写。

## 第三步：把结果和诊断一起放进 Context

当有内容时，Segment 的正文形状接近：

```text
# Skills

### Skill: agent-tutorial-diagrams [local/agent-tutorial-diagrams]
<完整正文>

Potentially relevant Local Skills...
<skills>
  <skill>
    <name>another-skill</name>
    <description>...</description>
  </skill>
</skills>
```

除了正文，Segment 还返回：

- `injected_skill_ids`：哪些 Skill 已注入完整正文；
- `referenced_skill_ids`：哪些 Skill 只展示引用；
- `skill_hits_by_source`：候选来自哪些逻辑 source；
- `skill_source_failures` 与 `skill_source_failure_types`：区分“没有相关候选”和“搜索来源出错”。

`SkillForgeRouter` 会隔离单个 source 的异常，并把该 source 当成本轮空结果。当前只有 Local source，因此它失败时没有第二个在线来源补位，但 diagnostics 仍保留失败证据。

## 文件修改以后怎样进入下一次搜索

`LocalSkillCatalog` 默认启动 `SkillFileWatcher`。workspace 下的 `SKILL.md` 新增、修改或删除时，Watcher 解析它属于哪个 source，Registry 只失效对应 slice，LocalPool 在锁外重建新索引，最后原子交换。

正在执行的搜索会继续使用自己已经捕获的 Registry/BM25 快照；后续搜索使用新索引。Watcher 启动失败时，Catalog 仍可使用已有缓存，也能显式调用 `invalidate_skill_cache()`。

<callout emoji="❗">
**这里没有自动进化闭环。**文件变化能够刷新检索，不代表 Pico 会根据一次任务自动生成、评测并激活新 Skill。当前 `pico evolve` 的 `skill` candidate kind 仍缺少可通过 G5 的保留 Runtime Skill 路由 fixture 与 evaluator。
</callout>

## 从测试验证理解

- `tests/test_skill_forge_local_pool.py`：BM25、CJK 分词、always 过滤与原子重建；
- `tests/test_skill_router_sr1.py`、`test_skill_router_sr2.py`：Local source、failure isolation 与 diagnostics；
- `tests/test_skill_segment_builder.py`：activated、reference、abstain 与 Segment metadata；
- `tests/test_skill_forge_refs.py`、`test_skill_ref_resolution.py`：相对资源与 `skill_read`；
- `tests/test_agent_loop_injected_skill_ids.py`：注入 Skill id 怎样进入 Turn 证据；
- `tests/test_phase_a_default_engine.py`：默认 Context Engine 注册 `skill_read`。

## 20 分钟代码练习

1. 在一个临时 Workspace 下创建 `skills/demo/SKILL.md`，写清 name 与 description。
2. 在 `SkillRegistry.list_all()` 找到它的 source、name 与 path。
3. 用包含 Skill 名称的 query 追到 `LocalPool.search()` 与 `RouterHit`。
4. 改变 query，让它分别落到 activated、reference 和 abstain。
5. 修改 SKILL.md 后调用失效流程，确认下一次搜索读取新内容。

完成后回答：为什么 always Skill 必须从 BM25 候选里过滤？为什么 injected id 只能证明正文暴露给模型，不能证明模型真的采用了这套方法？

## 本章复盘

- [ ] 能说明 Skill 与 Tool 的分工

- [ ] 知道 workspace、local_dirs 与 builtin 怎样进入 Registry

- [ ] 能画出 Registry → LocalPool → LocalSkillSource → Resolver

- [ ] 能区分 always、activated、reference 与 abstain

- [ ] 知道当前 Runtime 只装配 Local source

- [ ] 能用 diagnostics 区分无候选和 source failure

- [ ] 不会把文件热更新写成自动 Skill 进化

## 接下来读什么

- [P06A｜Memory](https://icnoljnkix43.feishu.cn/wiki/AVOzwjVuPiee3qknwfZc43Uxnih)：回看可召回资料的读写与 Pico-Myna 边界；
- [P07｜Tools 与执行边界](https://icnoljnkix43.feishu.cn/wiki/FvphwDl6AipgzMkozHNc3kQAnib)：Skill 指导模型行动后，工具调用怎样真正执行；
- [P11｜PicoBench](https://icnoljnkix43.feishu.cn/wiki/XTOEwv9vhig1IikThC8cOJXEnrg)：怎样验证 Skill 被注入以后是否真的改善任务结果。