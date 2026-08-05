# 10 Evolver：自进化闭环，以及它没做到的那件事

> 教学快照：代码正文按 `76d3761`（PR #47）阅读，第一轮证据核实至 `b65f962`（PR #53）；当前检查点为 `b215c13`（PR #56）。PR #56 已加入 small-real harness，但未跑出真实模型 verdict。差异与 M 编号见 [references/metrics-ledger.md](references/metrics-ledger.md)。

读完这一篇，你应该能回答：

- 让 agent 改自己的代码，最容易在哪四个地方作弊或自欺
- 三道门分别拦什么，为什么「晋升」和「可对外宣称」是两个独立判定
- 封存测试集怎么做到物理隔离而不是靠自觉
- 候选补丁凭什么被允许写进 git，激活为什么必须有人签字
- 这一章最大的诚实点：真实的进化运行，至今没有跑过

## 一、问题：一个会给自己打分的系统

设想一个循环：跑一批任务，找出失败的，让模型分析原因并改 agent 自己的代码，改完再跑一遍，比之前好就留下。听起来顺理成章，四个坑一个比一个隐蔽。

**坑一：分母会动。** 候选跑了 90 个任务，其中 6 个因为服务超时没跑完。如果算平均分时把这 6 个剔除，分母从 90 变成 84，分数自动虚高。更糟的是这种「失败即剔除」有方向性：难任务更容易超时，剔除的恰好是最难拿分的那部分。`gates/fisher.py` 的模块注释给这个坑起了名字，fair-subset extrapolation trap，公平子集外推陷阱。

**坑二：改了但没生效，照样算赢。** 模型在某个分支里加了段逻辑，那个分支在这批任务里从没被触发过。成绩变好了，因为运行有随机性。这个候选被留下，下一轮在它基础上继续改，整棵树建在一次噪声上。

**坑三：拿测试集调参。** 每轮都看一眼留出集，挑表现最好的那轮当交付。跑二十轮，从二十个带噪声的测量里取最大值，这个最大值必然虚高（选择偏差），而且是系统性的。

**坑四：把「更好」和「显著更好」混为一谈。** 单次运行的通过率本来就有几个百分点的摆动。一个候选高了 2 个点，是真的改进还是抽样噪声？如果不区分，这个循环会在噪声上稳定地爬坡。

四个坑指向同一件事：一个能自我评价的系统，必须先解决「谁来当裁判」。Pico 的答案不是让模型更诚实，是把作弊路径在结构上堵死。

## 二、对照组：没有护栏的那条路

同一套方法论（`docs/specs/self-evolution-loop-sop.md`，下称 SOP）有两种执行方式，`pico/evolver/README.md` 把它们并排写了出来。第二种是把 SOP 文档直接交给一个 coding agent（比如 Claude Code），让它自己在仓库里走七步：读失败轨迹、挑失败原因、把候选写成 git 提交、手动跑 K 次评测、手算门算术。README 对这条路的定性只有一句：nothing enforces the protocol，封存纪律、固定分母、诚实的门算术全取决于 agent 的自觉，结果只能当探索性数据。

上游 SOP 自己也把这笔账记在了明处。映射文档（`docs/specs/self-evolution-loop-implementation.md` 第 5 节）引用了 SOP §8.2/§9.2 的原话：封存测试「还没建机制；过渡期靠纪律；评审者会挑战这一点」。这是上游自己承认的最尖锐的方法论债务。

第一种执行方式就是本章的主角：`pico/evolver/` 的编排器把整个漏斗写成代码。`orchestrator/loop.py` 的模块注释交代了动机：漏斗的形状从模型记忆里拿走之后，弱一点的驱动模型（注释点名 Qwen / Kimi）也能跑循环。这条对照在面试里很好用：同一份 SOP，人肉执行产出探索性数据，编排器执行才产出可审计证据；前者仍然有用，它是给还没有插件的新 benchmark 探路的最快方式。

## 三、一次运行的全貌

`pico evolve` 有四个子命令，`pico/evolver/cli.py` 顶部的一句话版本最准：

```
run      cold start -> rounds -> unseal, resumable at any interruption
check    validate config / models / bench setup without running anything
status   inspect progress (never reveals sealed test numbers)
finalize end the run now and unseal (one-way)
```

`check` 只做便宜的校验：配置、模型、bench 就绪性，外加对被测端点的一次小探针补全，一个任务都不跑。`run --smoke` 在隔离的 `<work_dir>_smoke` 里跑一次接线验证，AppWorld 下确定性地压到 3 个训练任务加 1 个不重叠的封存任务，几分钟出结果，绝不花掉完整数据集（README Quickstart 节）。

`run` 是三阶段：

**阶段一，冷启动。** 未改动的原始 agent 在全部训练任务上跑 K 次（K 是每个任务的重复评测次数，确认标准是 K=3），作为对照基线。它是幂等的，只补缺失的试验文件，中断了重跑不会重复消耗。

**阶段二，多轮循环。** 每轮走 SOP 的七步（`loop.py` 模块注释与映射文档第 3 节的对齐关系）：① 诊断失败轨迹，归纳出若干「为什么失败」的类别并入跨轮累积的失败地图；② 让模型针对最值得攻的几类设计候选补丁，设计出口处就有三道免费剪枝（AST 编译、入口模块导入冒烟、信标存在性检查，都在 `benchmarks/appworld/evolve/editor.py`），没过的候选根本不会产出；③ 零命中预检（用候选自报的触发正则对历史轨迹预筛），当前默认关闭，理由写在映射文档第 6 节：Gate-b 已经保证没触发的机制拿不到信用，预检只省预算，先收集数据再定默认值；④ 清单门 G5，过了才作为真实 git 子提交落盘；⑤ 便宜筛选，SWE 线是 K=1 锚点集筛选，AppWorld 线是 K=3 聚焦子集探针（锚点集是从训练集选出的小任务子集，构成是破冰任务加边界任务加哨兵对照，`AnchorParams` 默认 5+7+12）；⑥ 存活者做 K=3 全量确认，进三道门；⑦ 选下一轮的父节点并写判词。

**阶段三，解封。** 循环期间一次测试集都没跑过。全部结束后才用留出集给每轮的交付物补测，算保持率，然后盖一个单向的解封戳。

预算和停机都是硬编码的循环控制，不靠模型自律。预算（`orchestrator/config.py::Budget` 默认值）：每轮最多攻 2 类原因，每类最多 3 个候选，另加 1 个确定性重组；加载期就校验，小于 1 直接拒绝启动（`launch/config.py`）。停机（同文件 `Termination` 默认值）：连续 10 轮没人在训练集上打过固定的 vanilla 基线就停（耐心信号，对比对象永远是 vanilla，不是上一轮父节点），硬上限 20 轮，连续 5 轮全员报错走独立的错误计数停机，报错轮不烧耐心，避免基础设施故障伪装成「探索已穷尽」。

成本结构也值得背下来（README 原文）：一次真实运行以小时到天计，大头是被测 agent 的评测，不是循环自己的 LLM 调用。冷启动是训练集乘 K（例如 90x3）次试验，每个通过筛选的候选还要付大约一次全量乘 K 的确认；循环自己每轮只有几十次诊断调用、每候选一次设计调用、几次判词调用。

### 一个候选的一生

把第 ②④⑤⑥ 步接起来看一个具体对象怎么流过整条流水线，每个环节都有磁盘上的实物：

1. **出生在一次性 worktree 里。** 设计沙箱是 detach 在父提交上的 git worktree（`sandbox.py`），驱动模型在里面用 JSON 动作干活：`bash`、`write_file`、`read_trajectory`、`done`，最多 22 轮，连续 4 次只读 bash 会被强制要求动手改文件（`editor.py` 默认参数）。
2. **设计出口三连检。** 改动先过 AST 编译；再在沙箱里导入 `benchmarks.appworld.agent_cli` 做导入冒烟，因为 AST 查不出坏 import，那种候选会把整场评测变成基础设施噪声；Python 代码改动还必须带信标。任一步失败，返回值是 None，这个候选连节点都不会有。
3. **G5 预检，然后才有提交。** 清单校验通过后，`production.py::make_git_commit_apply_fn` 用 commit-tree 在父提交上做出真实子提交，节点 id 形如 `v3-c2-a1f4`（轮次、序号、4 位十六进制盐），提交信息是 `evolver: round N candidate off <parent>`。
4. **探针与确认各有专名目录。** 聚焦探针的输出目录叫 `<node_id>_focused`，全量确认叫 `<node_id>_confirm`。后者的命名由 `strategies.py::confirm_job_name` 单点定义，因为诊断步骤之后要按同一个名字回读这个目录里的轨迹，注释原话说这是跨模块契约，不是局部细节。命名当契约管理，是这条流水线里最省事的一个可迁移经验。
5. **判决落三处。** 三道门的结果写进节点账本 `nodes/v3-c2-a1f4.json`（身份、git 锚点、终态、门统计），轮次日志追加一行并 fsync，`findings.md` 加一节人类可读记录。
6. **接受态多一个包。** 证据合格的候选在 `activation/<candidate_id>/` 下拿到一个激活包，初始状态 `pending_human`，此后归人管（见第六节）。

## 四、机制一：三道门各拦一个坑

三道门顺序固定，前一道不过后一道不跑（`gates/pipeline.py::run_gates`）。

### Gate-f：这次测量算不算数

它先问「数据够不够格被解读」。判据函数 `scoring.py::measurement_validity` 逐任务归类，然后一次性定性：

```python
if ev.failure is MeasurementFailure.provider:
    provider_failures.append(task_id)
if ev.failure is MeasurementFailure.infrastructure or ev.infra_attempts > 0:
    infrastructure_failures.append(task_id)
if ev.failure is MeasurementFailure.inconclusive or ev.attempts < expected_attempts:
    inconclusive.append(task_id)
...
if provider_failures or infrastructure_failures:
    status = MeasurementStatus.failed
elif missing or inconclusive:
    status = MeasurementStatus.inconclusive
```

两臂（候选与对照）任一出现 provider 或基础设施失败，整个判定直接是 failed；有缺测或不足 K 的，判定 inconclusive。这个区分把「测量无效」和「分数低」分成了两种失败，无效的测量永远不会被换算成一个低分继续参与比较。

关键设计是分母固定：`gates/fisher.py::train_mean` 的分母永远是 `len(task_ids)`，缺测的任务贡献 0.0 而不是被剔除，docstring 明写剔除会缩小分母、高估 pass@1。坑一由此堵死。

上游失败还有一条救援阶梯（`scoring.py::eval_with_infra_rerun`，`max_reruns=2`）：还带着基础设施失败的任务最多自动重跑 2 次，生成带序号的 `_infra_rerun{1,2}` 重跑目录，保留规则是「完整合法的测量优先，两者都是基础设施失败时取失败次数更少的那次」（`prefer_rerun_measurement`）。这条规则在编排层和磁盘读回层各实现一次（后者在 `benchmarks/appworld/evolve/adapter.py::read_kept_out_dir`），两处必须一致。救不回来的失败带着出处进 Gate-f，照旧 fail-closed。

### Gate-b：这段补丁真的执行了吗

这道门解决坑二，思路是让候选代码自证执行。设计提示词强制要求补丁埋一个信标，而且约束写得很具体（`editor.py`）：

```python
_BEACON_REQUIREMENT = (
    "\nINSTRUMENTATION (required for python edits): the new code path MUST call\n"
    "    from pico.evolver.activation.ledger import activation_beacon\n"
    "    activation_beacon('<your tag>', '<site>')\n"
    "at the exact place your mechanism fires (INSIDE its trigger condition, NOT at "
    "import/module level — a beacon that fires on every task carries no attribution "
    "signal). ..."
)
```

信标必须放在触发条件内部，模块级的信标每个任务都会响，没有归因价值。信标本身是个环境变量控制的空操作，评测之外一分钱不花（`activation/ledger.py::activation_beacon`）。存在性检查是字节串匹配（`_has_beacon`：`.py` 文件里找 `b"activation_beacon("`）；纯提示词或字符串常量的改动豁免，判据是 `_code_changed` 把所有字符串常量替换成占位符后比较 AST，真有代码形状变化才要求信标。豁免存在的原因很实际：AppWorld 的 agent prompt 就住在 `agent_cli.py` 里，纯改 prompt 的候选没有可挂信标的执行点。

读回端的三态语义是这道门最讲究的地方（`activation/ledger.py`）：

```python
def read_fired_tasks(out_dirs, task_ids) -> "set[str] | None":
    """...
    Returns None when NO out-dir carries the collection marker — no
    instrumentation data means Gate-b must fail OPEN (skip attribution), not
    reject everything. With the marker present, an empty set is an honest
    "the mechanism never fired anywhere" and Gate-b correctly credits nothing.
    """
```

没有采集标记返回 None，表示这次根本没有埋点数据，此时 Gate-b 必须 fail-open 跳过归因而不是把所有候选毙掉；有标记而集合为空，是一个诚实的「机制从未触发」，这时它一分不给。这个区分是「没测到」和「测到了没有」的区别，混淆任何一个方向都会出错。

诚实边界也写在规范里（映射文档 Gate-b data chain 行）：归因只到「存在级」，Gate-b 证明的是候选代码里的某个信标在某任务上执行过，不能证明这个信标恰好在机制的触发条件内。一个放错位置的无条件信标会让这道门退化成空操作，此时晋升仍然要靠全量训练集的胜出兜底。

### Gate2：更好，还是显著更好

用的是逐任务通过率差值的配对 z 检验（`gates/paired.py`）：

```python
diffs = [_rate(candidate_evals, t) - _rate(control_evals, t) for t in task_ids]
mean_lift = mean(diffs)
n = len(task_ids)
se = stdev(diffs) / math.sqrt(n) if n > 1 else 0.0
...
promoted = verdict is EvaluationVerdict.accepted
credited_2sigma = promoted and z >= z_threshold
```

两个字段分离是这道门的核心判断：`promoted` 只要求候选均值超过对照，用于循环内选下一轮父节点；`credited_2sigma` 要求 z 达到 2，才可以对外宣称。docstring 里记了一个真实案例：手动第 3 轮一个叫 budgetnudge 的候选提升 6.4 个百分点被收入，但配对 z 只有 1.71，没到 2σ，于是它进了库、没有获得可宣称的信用。还有个边界处理值得记：所有共享任务同幅度提升时 se 为零，这种确定性胜利报 z 为无穷，不会因为除零翻车。

配对检验本身也是选择：同一批任务上比较候选与对照，把任务难度这个最大的方差源消掉，同样的效应所需样本比不配对少很多。Gate-b 收窄过合格集时，配对统计跑在子集上，但晋升是双条件：子集上的配对判定成立，并且全量训练集均值不输对照（`strategies.py`，`promoted = gate.promoted and full_mean >= control_full_mean`），子集可以主张信用，不能以牺牲全集为代价。另外别把这里的阈值和第一阶段聚焦筛选用的 Fisher 精确检验（`FocusedFisherGate`，alpha=0.05）搞混，两者用在不同阶段。

坑四由此堵住，而且堵法很诚实：不是禁止把没到显著性的候选留下（那会让循环寸步难行），是把「能用来继续走」和「能拿出去说」分成两个字段。

## 五、机制二：封存测试集的物理隔离

坑三的解法在架构上最漂亮。映射文档的说法是「机制而非纪律」，上游靠纪律欠下的那笔债（第二节引过），在这里被五处代码补上。

**启动期泄漏断言。** 编排器构造时就检查锚点集、训练集与封存测试集的交集（`sealed/runner.py`）：

```python
def assert_no_test_leak(*, anchor_task_ids, train_task_ids, sealed_test_ids) -> None:
    """Fail if any sealed test id is present in the anchor or train sets."""
    test = set(sealed_test_ids)
    anchor_leak = sorted(test & set(anchor_task_ids))
    train_leak = sorted(test & set(train_task_ids))
    if anchor_leak or train_leak:
        raise TestLeakError(f"sealed test ids leaked into decision sets: ...")
```

任务集合层面还有第二道：AppWorld 插件在装配期就对训练与测试任务列表求交集，非空直接 `ValueError`（`entry.py`，报错文本 train/test task sets overlap）。

**决策路径上没有回传口。** 封存打分函数把结果写进封存目录，然后返回 `None`：

```python
def score(self, node: HarnessNode, round_index: int) -> None:
    """Blind-score ``node`` on the test set; persist, return nothing."""
```

不是「约定不要用」，是函数签名上就没有值可用。

**status 命令从不读封存目录。** `launch/runner.py` 的模块 docstring 明写这条，实现里全程只读日志、节点与摘要。想中途偷看测试分数，没有入口。

**解封是单向戳。** 解封时先盖戳再写报告（`runner.py` 的注释解释了顺序：戳才是阻止续跑的东西，先写报告后盖戳会留一个既看过测试数字又还能续跑的窗口）。戳落下之后，默认路径上 `run` 拒绝续跑；存在一个显式的 `--force` 逃生门，配置指纹漂移的拒绝同样有，绕过是操作者的署名决定，不是系统的默认行为。

**交付物按训练集最优选，不按测试集最优选。** 这条防的是选择偏差（`sealed/runner.py::unseal_retention`）：

```python
promoting = [rec for rec in journal_records if ...]
if promoting:
    best_rec = max(promoting, key=lambda r: (r["next_parent_train"], -r["round_index"]))
```

注释给了理由：在多次带噪声的封存测量上取最大值，会因为选择而虚高收益（winner's curse）。逐轮曲线只作展示用途。过拟合的表现形式是一个诚实的低保持率，不是一个被悄悄换掉的交付物。

保持率的定义也干脆：测试集提升除以训练集提升；训练集提升不为正或缺测时是 None，不硬算。封存打分同样吃分母纪律：pass@1 的分母是完整测试集任务数，缺测算 0。

还有个反直觉的实现选择：整个循环期间一次测试都没跑，所有封存打分都发生在解封阶段。之所以能这样，是因为每轮的交付物都是持久的 git 提交，事后可以逐一重建再补测。

## 六、机制三：补丁进 git，激活要签字

候选不是内存里的 diff，是真实的 git 子提交，还带一个 `refs/evolver/*` 引用。这带来两个好处：可复现（任何时候能 checkout 出那一版）、可审计（每个提交都能逐行 review）。

进 git 之前有一道清单门 G5（`candidate_manifest.py`）。候选清单记录标签、补丁位置、目标文件、改动前后的 sha256、补丁摘要、fixture 与评估器的绑定、激活策略。这里的 fixture 和评估器都是可执行对象，不是描述字符串：fixture 是校验快照与清单一致性的函数，评估器是从原始测量重算判决的函数，两者都要能在 `candidate_evidence.py` 的 `FIXTURE_BINDINGS` / `EVALUATOR_BINDINGS` 表里查到才算数。G5 逐项校验：标签是否受支持、绑定是否可执行、补丁位置是否属于该标签允许的集合、目标文件与哈希是否一致、目标文件是否真的有内容变化、路径是否越出可变白名单、配置类标签是否只碰配置后缀、是否触碰模型权重后缀。不过就是 `rejected_at_manifest`，**不创建提交**。

六个标签里只有 `runtime` 能过 G5，这个约束不靠人记，写在数据类的构造校验里：

```python
def __post_init__(self) -> None:
    if self.supported and (not self.fixture or not self.mutable_paths or not self.evaluator):
        raise ValueError(f"Supported label {self.label.value!r} requires fixture, allowlist, and evaluator")
    if not self.supported and not self.unsupported_reason:
        raise ValueError(f"Unsupported label {self.label.value!r} requires a reason")
```

受支持必须有三件套，不受支持必须给理由，另外五个标签各自带一条不受支持的理由（M7）。这是刻意的 fail-closed：schema 里保留它们让证据词汇稳定，但没有可执行绑定就不能声称支持。能力声明跟着可执行绑定走，不跟着 schema 走，这条可以直接搬去任何插件系统。

可编辑路径的白名单只有两个文件（`benchmarks/appworld/evolve/sandbox.py`）：

```python
WHITELIST_PREFIXES = (
    "benchmarks/appworld/agent_cli.py",
    "benchmarks/appworld/tool.py",
)
```

失效的前缀会导致拒绝启动（`launch/contract.py::validate_whitelist`，用 `git ls-tree` 在基线提交上核对每个前缀真能匹配到文件）。这条约束背后是一次真实事故，docstring 原话：

> A dead prefix does not error at run time — the designer's edits are silently reverted as out-of-whitelist and every candidate arrives empty, which once cost a full run.

白名单之外还有一道独立的不可变内核（`applier/path_guard.py::IMMUTABLE_PATTERNS`），把评分器和进化器自身的目录挖出来：`pico/evolver/` 整棵树、`benchmarks/appworld/evolve/`（含 `grade.py`）、`batch.py`、测试与依赖锁文件都在内。评分实现恰好位于设计者的白名单树内部，所以必须显式排除，注释直说了后果：能改 `batch.py` 的候选可以重塑自己的分母。

激活是另一件事。README 第一段就把话说死：晋升选出的是运行内的候选，不等于激活；审阅与激活始终是人工的。状态机只有五个状态，转移表把路径钉死（`activation/artifacts.py`）：

```python
_TRANSITIONS = {
    ActivationState.ineligible: frozenset(),
    ActivationState.pending_human: frozenset({ActivationState.ready}),
    ActivationState.ready: frozenset({ActivationState.activated}),
    ActivationState.activated: frozenset({ActivationState.rolled_back}),
    ActivationState.rolled_back: frozenset(),
}
```

`pending_human -> ready` 强制要求非空的 `human_actor`，校验函数在重放历史时缺人名直接抛错；`human_review` 策略的标签不允许把 `requires_human` 关掉。激活动作本身（`set_activation_state`）不动 live checkout、不 cherry-pick、不部署，docstring 明写。

激活包固定五个文件（`PAYLOAD_FILENAMES`）：`candidate_manifest.json`、`evidence.json`、`before.json`、`after.json`、`rollback.json`。回滚材料就是「改动前的快照字节」，`rollback_sha256` 直接等于 before 的摘要，且 before 快照必须逐字节等于父提交上那些目标文件的原始内容。接受态的证据还必须能从原始测量重算出一个通过的三门结果（`candidate_evidence.py` 会真的重跑一遍 `run_gates` 并核对 lift 与分数到 1e-12），伪造的 accepted 会在校验时失败。

## 七、机制四：中断了怎么办

模型是「产物即状态」。冷启动阶段的证据是试验结果文件，重跑只补缺；轮次阶段的证据是日志（`orchestrator/state/journal.py`），每轮一行 JSON、写完 flush 加 fsync。日志的容错很克制：只容忍最后一行损坏（被杀在写入中途正好留下半行，日志存在的意义就是扛这个），中间损坏直接抛错并报出行号，因为那意味着更严重的问题，历史已不可信。

恢复时会重放终止计数、父节点、轮次索引、父分数，并把每个晋升父节点的提交哈希重新登记进节点注册表，避免评测 checkout 到未知版本；跨轮累积的失败地图也从磁盘重读，不会被截断回空。

配置指纹是另一道闸（`launch/state.py`）：整份配置按 key 排序做规范化 JSON，取 sha256 前 16 位，恢复时不一致就拒绝，理由是两臂不再可比。密钥在快照落盘前被替换成常量 `<redacted>`（键名含 key 的字段，`api_key_env` 除外），注释点明用常量的原因：轮换密钥不该误触发漂移拒绝。元数据文件本身全部走「写临时文件再原子改名」，崩溃不会留下毒害下次恢复的半个 JSON。运行目录还有非阻塞文件锁（`.<work_dir 名>.evolution.lock`），防两个进程同时跑同一个运行。

## 八、取舍：为什么不做 X

**为什么不让循环自己跑封存测试来早停？** 那就等于把测试集变成训练信号，坑三立刻回来。代价是循环内看不到泛化情况，只能靠训练集和哨兵任务（哨兵是每个候选都要陪跑的回归对照任务，见第九节）。这个代价被接受了。

**为什么晋升不要求 2σ？** 要求了循环就几乎走不动：单次通过率摆动本来就有几个百分点，样本量在这个规模下很难稳定过 2σ。解法是把两件事分开，晋升用均值、宣称用 2σ，两个字段都写进日志。这比「降低阈值假装显著」诚实得多。

**为什么只有一个标签能过 G5？** 因为另外五个没有可执行的 fixture 和评估器。可以让它们「先支持着」，但那样 G5 就变成了走过场。fail-closed 的代价是能力面窄，收益是没有一次通过是虚的。

**为什么默认对照臂冻结在冷启动，不每轮重测？** 每轮重测对照大约要多付一倍评测费（README 给的量级是 ~2x eval cost）。冻结的代价写在 `gates/policy.py::FrozenColdStartBaseline` 的 docstring 里，cross-time-invalid：后期轮次在和一个可能已处于不同状态的运行环境比。代码注释直接承认这是成本约束下的回退，不是方法论正确的选择；端点吞吐会漂移的长运行应配置 `baseline_mode: same_session`，让两臂永远在同一时间窗测量。

**为什么威胁模型不做到对抗级？** 文档写得很直白：这些守卫拦的是 LLM 设计者抄近路，不是拦一个坚决的对手。候选代码与评分器同进程运行，benchmark 的 oracle 通过 HTTP 可达，原则上存在内存篡改或探测 oracle 的可能。结论也写在文档里：在一次性容器或虚拟机里跑，凭证要限权，引用任何分数之前先逐行审阅晋升的提交。承认边界比假装安全强。

## 九、真实翻车：六个都写在注释里

这一层的注释是全库最像事故档案的部分，挑六个。

**失效的白名单前缀吞掉一整轮。** 上面引过的那条，现在改成启动期拒绝。

**三个哨兵任务漏掉 58% 的回归候选。** 用少量稳定任务当回归护栏，看起来合理，实际过度触发型回归集中发生在边界任务上（脆弱的通过最先翻掉），纯稳定哨兵系统性失明；`loop.py::_sentinels_for` 的注释记了实测：一个让 58% 的原通过任务回归的候选，从 3 个稳定哨兵旁边溜了过去。修法是扩到 12 个（6 稳定加 6 边界，`AnchorParams` 注释）并按节点 id 哈希轮换，没有一套固定对照能被连闯两次。

**子集均值当分数用会污染整棵树。** Gate-b 收窄了合格任务集之后，如果把子集均值当成候选分数，会因为分母不同而污染「是否超过基线」的判断、父节点选择和日志曲线。修法是分数永远用全量训练集的固定分母，晋升是双条件（第四节）。`strategies.py` 的注释标注了出处：review round-2 P0-4，某轮评审发现的问题。

**同名节点继承了上一次死掉的运行的产物。** 崩溃续跑会用新候选重跑那一轮，如果节点 id 没有随机盐，就会复用死运行的输出目录、会话和引用，污染评测。修法是节点 id 加 4 位十六进制盐（`production.py`，`v{round}-c{n}-{salt}`）。

**快探针骗过慢后端。** 预检最初用一个 16 token 的探针测模型可用性，秒回就放行；`precheck.py` 的 docstring 记下了实测数字：共享后端 3.5 秒回探针的同时，68% 的真实试验在 900 秒超时上限上爆掉。修法换成约 300 token 的真实生成探针，测的是解码吞吐而不是可达性，低于每秒 12 token 的地板就拒绝开轮（12 tok/s 是 SOP 的健康标准「300 token 在 25 秒内」换算来的，观测到的健康带是 12-33 tok/s）。

**死掉的驱动伪装成「什么都没设计出来」。** 设计调用抛异常时早期实现静默返回空，一整个 smoke 轮产出零候选且毫无痕迹（`editor.py` 注释，记着日期 2026-07-09）。修法是把错误文本塞进候选摘要槽位（driver error: ...），让「驱动死了」和「真的没设计出来」在日志里可区分。

这六个的共同点：都不是崩溃，都是「看起来在正常工作」。自进化系统的 bug 大多长这样，所以门和护栏才要一层层加。

## 十、怎么被验证，以及没被验证的那件事

V-E0 是 301 项（M2），命令 `make verify-evolver`，覆盖公开 CLI 面与就绪校验、日志与中断与恢复与状态与终结、四态证据（accepted / rejected / failed / inconclusive）、G5 与不可变面、门算术与基础设施重跑、候选提交与信标、激活与回滚产物、逐字节稳定的摘要，以及一个跨进程的生命周期 fixture（起一个运行、换进程按同一日志续跑、两次全新进程读状态、终结两次，并证明摘要文件逐字节不变）。代表性测试文件在 `docs/architecture/evolver.md` 列了名：`tests/test_evolver_candidate_manifest.py`、`test_evolver_candidate_evidence.py`、`test_evolver_activation_artifacts.py`、`test_evolver_gates.py`、`tests/integration/test_evolver_lifecycle_e2e.py`。

然后是这一章必须写在明处的话：**V-E0 全部由 fixture 驱动，它证明生命周期与证据逻辑，不证明真实改进。** 文档原文是 V-E0 spends no live model calls and must not be reported as a production benchmark result。架构文档还专门列了「它不证明什么」：全尺寸生产运行、当下真实 Provider 可用性、release commit 上的真实留出保持率、对恶意候选代码的安全性、任何不受支持的标签、自动改进、生产激活，七条全排除在外。

一次小规模的真实进化运行至今没有跑过，这是项目的 P0 阻塞项之一（project-status.md P0 第 5 条）。跑过的是一次真实的冒烟：冷启动、续跑、一整轮真诊断真设计真提交、聚焦探针加确认、晋升、终止，README 对那次晋升的记法是 promoted with an honest credited=False，即进了库但没拿到可宣称的显著性信用。没跑过的是 90 个任务乘 K=3 的多轮规模，以及真实 benchmark 上的解封与保持率路径。

## 十一、预演追问

**「自进化听起来很危险，怎么保证不失控？」**
三层边界。第一，改动面被白名单锁死，只有两个文件可编辑，评分器和进化器自身在不可变内核里，agent 改不了给自己打分的代码。第二，晋升不等于激活，循环产出的是带证据的候选和真实 git 提交，激活是独立状态机且强制人工签字，激活动作本身不碰运行中的代码。第三，威胁模型我们写得很明确：这些守卫拦的是模型抄近路，不是拦坚决的对手，候选代码和评分器同进程，所以文档要求在一次性容器里跑并逐行审阅晋升的提交。

**「怎么防止它自己给自己打高分？」**
四个具体的坑各有对策。分母作弊：训练均值分母固定为任务总数，缺测算零不剔除。改了没生效也算赢：要求补丁在触发点埋信标，读回时区分「没有埋点数据」和「埋了但从未触发」，后者一分不给。拿测试集调参：测试集物理封存，打分函数写盘且返回 None，状态命令从不读它，解封是单向的，而且交付物按训练集最优选不按测试集最优选，防选择偏差。噪声当改进：配对 z 检验，晋升与可宣称是两个独立字段，达不到 2σ 的候选可以留在循环里但不能对外声称。

**「三道门具体怎么判？」**
按顺序。第一道判测量本身算不算数，任一臂出现 provider 或基础设施失败直接判失败，缺测或次数不足判结果不确定，基础设施失败最多自动重跑两次，保留规则取完整测量优先、同为失败取失败次数少的。第二道判归因，候选代码里的信标有没有在任务上真的触发，没触发的任务从合格集里剔除，全都没触发就直接拒绝；这道门有个刻意的 fail-open：完全没有埋点数据时跳过归因而不是全毙。第三道判统计，逐任务通过率差值的配对 z 检验，均值超对照即可晋升，z 达到 2 才算可宣称的信用；配对统计跑在收窄后的子集上时，晋升还要求全量均值不输对照，子集不能以牺牲全集为代价拿信用。

**「真跑出过改进吗？」**
诚实答：没有。教学基线的进化门有 301 项检查，当前检查点是 319 项（M20），但全部是 deterministic/fixture 证据，证明生命周期和证据逻辑正确，不证明真实改进。PR #56 已经补齐 small-real subject、不可变 grader、setup、resume、finalize 和发布层接线，但没有记录一次真实模型完成的 verdict。accepted、rejected 或可复现 no-improvement 都可以是合法结果，Provider 或基础设施失败不算。我更愿意先把「不会骗人」这件事做扎实，再去追一个好看的提升数字，因为一个能自我评价的系统，先要解决谁当裁判。

**「为什么要写编排器，不直接把方法论文档丢给 Claude Code 让它自己跑？」**
两条路我们都留着，README 里并排写的。直接驱动是原型最快的路，特别适合给还没有插件的新 benchmark 探路，它产出的失败分类、白名单、评分器接线经验直接喂给插件开发。但那条路上没有任何东西强制执行协议，封存纪律、固定分母、门算术全靠 agent 自觉，结果只能当探索性数据。编排器把这三样变成代码：封存打分函数返回 None，分母写死在均值函数里，门顺序写死在流水线里。上游 SOP 自己把「封存靠纪律」记成最大的方法论债务，还预告评审者会挑战它；机制化恰好把这笔债在我们这边清掉了。

**「为什么把这套东西做成通用的，而不是写死在一个 benchmark 上？」**
职责切在核心与 benchmark 插件之间：核心管轮次、预算、候选图、门的顺序、封存、日志和激活；插件管任务切分、评分子进程、结果解析、基础设施标记、轨迹渲染和可编辑路径。这样换一个 benchmark 不需要碰门的逻辑。代价是接口的约束条件多，插件契约里有一批必须在启动期就 raise 的校验，比如训练与测试任务集不许重叠、白名单前缀必须能在基线提交上匹配到文件，这些都是被真实事故逼出来的。

## 口播稿

> Evolver 是这个项目里最有意思也最容易吹过头的部分，所以我先说边界：它有一道三百多项的验证门，但全部由 fixture 驱动，证明的是生命周期和证据逻辑，不证明真实改进，真实的规模化运行我们还没跑过。机制上它解决的是一个自我评价系统怎么不作弊。四个坑各有对策：分母固定，缺测算零不剔除；候选补丁必须在触发点埋信标，读回时区分没有埋点和埋了没触发；测试集是物理封存的，打分函数写盘且返回空，状态命令根本没有读它的入口，交付物按训练集最优选而不是测试集最优选，避免多次带噪声测量取最大值的选择偏差；统计上用配对 z 检验，而且把能否晋升和能否对外宣称拆成两个字段，达不到两个标准差的候选可以留在循环里但不能声称显著。候选是真实的 git 提交，进 git 之前先过一道清单门，六个标签里只有一个有完整的可执行绑定，其余五个 fail-closed。晋升不等于激活，激活是独立状态机，强制人工签字。上游方法论把封存测试靠纪律执行记成自己最大的债务，我们把它做成了机制。威胁模型我们也写清楚了：这些守卫拦的是模型抄近路，不是拦对手。

## 复习路径（10 分钟）

1. 背四个坑和四个对策，这是这一章的骨架。
2. 用「一个候选的一生」串起七步：沙箱设计、三连剪枝、G5、子提交、探针、确认、三道门、账本与激活包。
3. 讲得出 Gate-b 三态语义为什么必须区分「没有数据」和「有数据但为空」。
4. 记住封存隔离的五处落地，重点是「打分函数返回 None」和「按训练集最优选交付物」，加一句上游 SOP 靠纪律、我们靠机制的对照。
5. 默写 promoted 与 credited_2sigma 的区别，以及 budgetnudge 那个 6.4pp 但 z=1.71 的真实案例。
6. 把「V-E0 是 fixture 驱动、真实运行没跑过」这句话背熟，它必须主动说，不能等人问。
