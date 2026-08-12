# Pico 差异化与教学化改造方案

> 状态：v2 草案（已按 review 意见修订），待再次 review
> 目标读者：项目负责人、协作者、后续执行该方案的 AI agent
> 关联规则：本方案配套修改了 `AGENTS.md`，新增 §1.4「教学注释规范」（v2 改为 allowlist + marker 双条件）
> 修订记录：
> - v2：吸收 review 全部 P1/P2 意见——验收条件改分类 allowlist；everos 语义修正（fail closed，非映射迁移）；取消批量测试改名；数据/lockfile 不重生成；扫描基线可复现且仅作观察指标；教学模块双条件 + CI 一致性；修正测试文件数。

---

## 1. 背景与目标

Pico 是从 [EverMind-AI/Raven](https://github.com/EverMind-AI/Raven)（Apache-2.0）fork 而来的 Agent Harness，已获公司授权，并保留第三方许可与归属声明（`NOTICES.md` / `LICENSES/`）。当前代码在文件层面与 Raven 高度相似；同时我们希望把 Pico 发展为可用于校招教学的项目。

本方案在**不改变产品功能与对外行为**的前提下完成两件事：

1. **差异化**：清理未归类的产品品牌残留，让项目拥有独立、自洽的代码身份。不追求法证级抹除，也不为降低相似度而牺牲行为。
2. **教学化**：将核心模块重写为更优雅、更可读、带规范中文注释的教学级代码。

### 边界原则（不可逾越）

| 原则 | 说明 |
| --- | --- |
| 许可链不动 | `LICENSES/`、`NOTICES.md`、SPDX/Copyright 头（含 `ui-tui/src/banner.ts` 中 "Modifications Copyright (c) 2026 EverMind"）一律保留 |
| 历史证据完整 | 承担复现/归属说明的文档内容（如 TokenWise 教程中的 Hermes A/B 对照、MIT 来源说明）属于历史证据，不属于清扫对象 |
| 产品边界兼容且 fail closed | 配置、环境变量、CLI、RPC 边界的现有行为（含拒绝行为）不得改变；确需变化的进入独立的行为变化阶段并明确定义语义 |
| 相似度仅作观察指标 | difflib 相似度、字节相同数受注释/格式化影响大，不作为合并门或验收门 |
| 小步推进 | 每次只动一个模块/一个主题，可独立回滚，绝不大爆炸式重构 |

---

## 2. 现状基线（2026-08-09 扫描数据）

| 指标 | 数值 | 说明 |
| --- | --- | --- |
| 源文件与 Raven 同名对应 | 356 / 372 | 目录结构几乎一致（`raven/` ↔ `pico/`） |
| 字节级相同文件 | 52 | 含 `embedding_data.json`(481KB)、`snapshot.json`(87KB)、`knn_memory_example.json`(99KB)、`package-lock.json`、`tracing/store.py` 等 |
| 相似度 ≥ 0.95 | 189 | 几乎等于同一份代码 |
| 相似度 ≥ 0.80 | 269 | — |
| 测试文件 | **273 个 Python 文件，其中 260 个 `test_*.py`** | `tests/` 尚未分化 |
| 非许可链品牌残留 | 待按 §3 分类后统计 | `everos` 报错文案、`HERMES_TUI_LEVEL`、TUI 品牌文件 |
| 文档相似度 | `CONTEXT.md` 0.56 | 词汇表仍是 Raven 体系 |

**已处理干净的**：git 历史（首个 commit 即 "chore: establish Pico repository"，无 Raven 历史）；GitHub fork 网络（非 fork 按钮创建，无关联）；README / CHANGELOG（已是 Pico 叙述）。

**已知数据约束**：
- `pico/config/loader.py` 对 `everos` 旧配置的处理是**丢弃已退役字段 + memory.backend 不改动**，显式旧 backend 会在插件解析时 fail closed（`_plugin_stack.py` 抛出带迁移提示的 `PluginNotFoundError`）。这不是"映射到新键"，语义不得改写。
- `ui-tui/src` 中 43 个文件 import `@hermes/ink` 包，107 个文件含 Hermes 许可声明——这些是许可链/依赖标识，**不属于清扫对象**。

---

## 3. 扫描基线定义（可复现，观察指标）

相似度扫描用于**观察趋势**，不作为验收门。每次扫描记录以下元数据：

| 项 | 定义 |
| --- | --- |
| Pico 基线 | 固定 SHA（当前 `997b66e`；每次扫描记录当时 `HEAD` 与工作树状态 `git status --porcelain`） |
| Raven 基线 | 干净 checkout，固定 SHA（不使用带未提交改动的本地目录；此前本地 clone 有未提交改动且落后 `origin/main` 21 个提交，须以 `git clone --depth 1` + 固定 commit 重新拉取） |
| 配对规则 | `raven/<path>` ↔ `pico/<path>` 同路径配对 |
| 排除项 | `LICENSES/`、`NOTICES.md`、SPDX 头文件、`ui-tui/packages/hermes-ink/`、`package-lock.json` 等锁文件、`routing/*.json` 数据文件 |
| 算法 | `difflib.SequenceMatcher(None, a, b).ratio()`，记录 Python 版本 |
| 输出 | 相似度分布（>0.95 / >0.8 / 相同）、字节相同文件清单、趋势对比 |

执行方式：沉淀为 `scripts/lineage_similarity_scan.py` 入库（记录基线参数），由维护者手动运行，**不接入 CI 门禁**。扫描结果追加到固定日志（如 `docs/plan/lineage-scan-log.md`），每次一行：日期、Pico SHA、Raven SHA、各区间文件数、identical 数——用于跨阶段趋势对比，不作阻断判断。

---

## 4. 阶段一：低风险清理（分类制）

**核心变化（按 review）**：不再以"全树 grep 为空"为验收，而是对残留分类——只有"未归类的产品品牌残留"是清扫对象；许可链、历史证据、依赖标识一律保留。

### 4.1 残留分类框架

| 类别 | 范围 | 处理 |
| --- | --- | --- |
| A. 许可链 | `LICENSES/`、`NOTICES.md`、SPDX/Copyright 头（含 "Modifications Copyright (c) 2026 EverMind"）、`@hermes/ink` 包名与 107 个 Hermes 许可声明 | **保留，不动** |
| B. 历史证据 | `docs/tutorial-zh/` 中 Hermes A/B 对照复现、MIT 来源说明；`token_wise/EXPERIMENT_REPORT*.md` 中的 EverOS 复现上下文 | **保留，不动** |
| C. 依赖标识 | `package.json`/`package-lock.json` 中 `@hermes/ink` 依赖名、`babel.compiler.config.cjs` 等 | **保留，不动** |
| D. 产品品牌残留 | 运行时文案、日志、TUI 品牌画面中的 Raven/EverOS 品牌（不含上述三类） | **唯一清扫对象** |

**验收（D 类）**：对 D 类清单执行 `grep -rniE "raven|everos|hermes"` 按文件逐个核对，允许 A/B/C 类命中，D 类清零。

### 4.2 任务 D1：品牌文案清扫（仅 D 类）

| 文件 | 处理方式（语义不变） |
| --- | --- |
| `pico/cli/_plugin_stack.py` | everos fail closed 行为与迁移提示**保留**；仅当存在纯品牌文案（无功能语义）时才可调整措辞，且须同步更新断言该文案的测试 |
| `pico/config/loader.py` | **不改**。everos 退役字段丢弃、memory.backend 不改动、fail closed 语义均为当前正确行为 |
| `pico/token_wise/*.py` | 仅清理 D 类品牌表述；实验报告中的 EverOS 复现上下文属 B 类，保留 |
| `ui-tui/src/` | 仅 D 类品牌画面/文案；`HERMES_TUI_LEVEL` 处理见下 |
| 其余 TUI 文件 | 逐文件按 A/B/C/D 分类，仅处理 D |

**环境变量 `HERMES_TUI_LEVEL`**：改名属于**行为变化**（外部用户可能设置该变量），不放在本阶段。若纳入，须在行为变化阶段明确定义优先级：`PICO_TUI_LEVEL` 优先，`HERMES_TUI_LEVEL` 作为已废弃回退（读取兼容），并在 `CHANGELOG.md` 记录。默认建议：本阶段不动。

**实测盘点（2026-08-09，`chore/brand_cleanup` 分支）**：全仓扫描（排除许可链）后，**D 类纯品牌残留 = 0**——产品代码无 `raven`/`evermind` 字符串；`ui-tui/src/__tests__/branding.test.tsx` 已有断言 banner 不含 hermes 品牌。实际清扫仅 2 处注释措辞：`ui-tui/src/components/branding.tsx:138`、`ui-tui/src/entry.tsx:6-8`。保留项与上表一致（@hermes/ink 依赖、`HERMES_TUI_LEVEL`、everos 迁移逻辑、Hermes 算法复现引用）。

### 4.3 任务 D2：测试命名（取消差异化改名）

**按 review 取消**"为差异化而重命名测试"。理由：`Makefile`、`scripts/`、架构文档、教程大量引用具名测试路径（如 `Makefile` 中的 `tests/test_commit_lint.py`、`tests/test_picobench_*.py`、`tests/test_cli_evolve_commands.py` 等），批量改名会破坏验证门或静默缩小覆盖面。

调整为：
- 仅修**真正违反 §5.1/§5.2 命名规范**的文件；
- 每改一个，全仓检索并更新引用（Makefile、scripts、docs、tutorials），验证门覆盖面不变；
- 测试断言逻辑一律不动。

### 4.4 任务 D3：文档词汇表

- `CONTEXT.md` / `CONTEXT-MAP.md`：**实测已是 Pico 原生**（CONTEXT-MAP 标注 "Pico v1 implementation glossary"；CONTEXT 长度约为 Raven 版 1.7 倍、结构为 Pico 体系），无需重写；保留历史证据段落（B 类，如 "EverOS (historical)"、Hermes-faithful A/B 复现说明）。
- `docs/tutorial-zh/` 中的 Hermes 内容属 B 类，保留；仅清理 D 类。
- `NOTICES.md`：**补记 fork 派生链**——当前仅列 nanobot / hermes-agent / ink，未列直接来源 Raven（356 个同名文件）；补记 "forked from EverMind-AI/Raven (Apache-2.0)"（含其许可/NOTICE 文本，如缺）。属许可链维护，非清扫，与 §7「来源完整」验收一致。
- **验收**：词汇表为 Pico 体系；A/B/C 类内容完整；NOTICES 派生链完整。

### 4.5 明确不做的（按 review）

- **不重生成** `embedding_data.json` / `snapshot.json` / `knn_memory_example.json`——重生成会改变 routing 行为，且不应仅为降低字节相同数而做；保持原样，仅在观察指标中记录。
- **不重生成** `package-lock.json`——`npm install` 可能改变解析结果；保持原样。
- **不进行** 任何影响产品边界的改动（配置语义、环境变量、协议）。

**工时估算：0.5~1 天**（范围大幅收窄）。

---

## 5. 阶段二：教学级重设计

### 5.1 方向取舍

教学项目里「简单直白」优先于「抽象优雅」：

- 允许适度重复代码（DRY 退居其次，重复有助于读者建立模式感）；
- 长函数拆成有名字的小函数（每个函数只做一件事）；
- 公开 API 写详细 docstring（参数、返回值、异常、边界）；
- 关键路径加教学标记（`# 例：`、`# 为什么这里...`）；
- 结构必须比现状更清晰，而不是更抽象。

### 5.2 模块顺序与教学主题

| 序 | 模块 | 教学主题 | 约规模 |
| --- | --- | --- | --- |
| 1 | `tracing` | 可观测性：span/事件/存储（样板模块） | 小 |
| 2 | `session` | 会话生命周期与持久化 | 小 |
| 3 | `context_engine` | 上下文窗口与预算算法 | 中 |
| 4 | `agent/loop` + `checkpoint` | Agent 循环、检查点恢复 | 中 |
| 5 | `tui_rpc` | JSON-RPC 协议设计 | 中 |
| 6 | `channels` | 适配器模式、多端抽象 | 中 |
| 7 | `spine` | 调度器与 Turn 契约 | 中 |
| 8 | `evolver` | 自进化系统（可选，见 §9） | 大 |

> 8 个模块合计约 **3.3 万行 Python**。工时在 `tracing` 样板完成后重估，见 §8。

### 5.3 每模块交付物（教学要求）

1. **读者任务**：明确"这个模块教读者什么"，写在模块 docstring 中；
2. **数据流说明**：模块 docstring 用文字/伪代码描述数据流（谁调用、产出什么、边界在哪）；
3. **重设计**：按 §5.1 方向重构，边界更清晰、命名教学化、长函数拆分；
4. **教学注释**：按 `AGENTS.md` §1.4 规范写中文注释（模块 docstring 首行 `教学模块：`，且必须出现在教学 allowlist 中——见 §6）；
5. **测试**：该模块的测试随重设计同步更新/补齐，覆盖数据流主路径；全量跑该模块测试 + 相关集成测试，绿了才进下一个模块。

---

## 6. 质量保障机制

| 机制 | 说明 |
| --- | --- |
| 测试闸门 | 每次改动后 `uv run pytest tests/`（273 个 Python 文件、260 个 `test_*.py`）；每模块重写后跑该模块全部相关测试 |
| 教学 allowlist 一致性 | 教学模块 = **出现在 `docs/plan/teaching-differentiation.md` 的精确文件 allowlist 中** **且** 模块 docstring 首行为 `教学模块：`，二者必须一致；CI 校验 allowlist ↔ marker 一致性（防自声明豁免） |
| 产品边界守卫 | 配置/环境变量/CLI/RPC 行为（含 fail closed）用现有测试锁定；凡清扫涉及边界附近代码，**先补 fail-closed 特征测试锁定现状行为，再动代码**（覆盖率不足时先补测试后改）；行为变化一律走独立阶段 |
| 小步回滚 | 每模块独立提交，出问题只回滚一个模块 |
| 相似度扫描 | §3 定义，仅观察，不进 CI 门禁 |

---

## 7. 全局验收（按 review 建议的主线）

- [ ] **产品边界兼容且 fail closed**：配置兼容路径、everos 拒绝行为、迁移提示与现状一致，由现有测试验证；清扫触及边界代码前先补 fail-closed 特征测试，不新增行为变化；
- [ ] **教学模块达标**：每个教学模块有明确读者任务、数据流说明、教学注释与配套测试；
- [ ] **来源、许可与历史证据完整**：A/B/C 类内容（许可链、历史证据、依赖标识）无删改；NOTICES.md 派生链完整（补记 Raven 中间来源）；
- [ ] **D 类品牌残留清零**：按 §4.1 分类逐个核对；
- [ ] **相似度与字节相同数**：仅作观察指标记录趋势，不设硬性门槛。

---

## 8. 里程碑与工时

| 里程碑 | 内容 | 估算 |
| --- | --- | --- |
| M1 | `AGENTS.md` §1.4（双条件）+ 本方案 v2 评审通过 | 0.5 天 |
| M2 | 阶段一低风险清理（分类制） | 0.5~1 天 |
| M3 | 教学样板模块 `tracing` 重写完成，**据此重估阶段二总工时** | 0.5~1 天 |
| M4 | 阶段二其余模块（session → evolver） | **M3 后重估**（初版 4~6 天偏激进，以 M3 实测为准） |

---

## 9. 开放问题（待 review 拍板）

1. **`HERMES_TUI_LEVEL` 是否改名**：改名 = 行为变化（需定义 `PICO_TUI_LEVEL` 优先级 + 兼容回退 + CHANGELOG）。默认本阶段不动，是否单独立项？
2. **数据文件**：`embedding_data.json` 等保持原样（接受字节级相同），是否确认？
3. **教学范围**：覆盖全部 8 个模块还是先选 3~4 个（tracing / session / agent-loop / context_engine）？evolver（最大、最独特）是否纳入？
4. **教学 allowlist 粒度**：§5.2 的表按模块列，allowlist 落文件级（每个 `*.py`）还是模块目录级？CI 校验按哪个粒度实现？
5. **扫描工具**：`scripts/lineage_similarity_scan.py` 入库并锁定基线参数，是否认可（仅观察、不进 CI）？

---

## 10. 规则变更记录

本次配套修改 `AGENTS.md`：

- 目录表 §1 行补充「(teaching modules: §1.4)」；
- 新增 **§1.4 教学注释规范**（v2 修订）：教学模块 = **allowlist + docstring marker 双条件**（防自声明豁免），由 CI 校验一致性；教学模块放宽 §1.1，允许增加详细教学注释。§1.2 后续已调整为全仓注释语言不限，普通模块仍须遵守“只解释为什么”的稀疏注释规则。
