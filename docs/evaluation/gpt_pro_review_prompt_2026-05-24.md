# GPT Pro Review Prompt 2026-05-24

```text
你是 GPT Pro，请以资深工程 reviewer + benchmark 设计 reviewer 的角度审查这个 PicoBench 分支。

仓库路径：/Users/martinlos/code/pico
分支：codex/picobench-v3
重点文件：
- docs/evaluation/benchmark_handoff_archive_2026-05-24.md
- docs/evaluation/resume_benchmark_summary.md
- docs/evaluation/live_results_summary.md
- docs/evaluation/live_execution_log.md
- docs/evaluation/phase3_plan.md
- scripts/run_picobench.py
- scripts/run_picobench_runtime.py
- scripts/run_picobench_ablation.py
- pico/evaluation/cli_runner.py
- pico/evaluation/report_card.py
- pico/evaluation/validators.py
- benchmarks/picobench-core-v1.yaml
- benchmarks/picobench-agentic-native-v0.yaml
- benchmarks/picobench-agentic-v1.yaml

用户原始目标是：完成整个 benchmark 的开发和运行，最后基于 v3 和 benchmark 产出一段可以写进简历的 Pico 项目描述。用户现在怀疑 Codex 理解错了意思。

请重点 review：
1. “完成整个 benchmark 的开发和运行”到底有没有被满足？如果没有，缺口是什么？
2. Codex 把 30-task core live run 的 8 个 strict failures 当作 benchmark signal 留档，而不是继续修到全绿，这是否违背用户目标？
3. `agentic_native_memory_001` functional pass 但 strict 失败在 evidence bundle，这应该被视作 benchmark 未完成、runner bug、任务设计问题，还是可接受留档？
4. `scripts/run_picobench_ablation.py` 仍然是 plan-only，是否说明“整个 benchmark”还没有完成？如果要完成，需要补哪些 feature flags 或实验控制？
5. `docs/evaluation/resume_benchmark_summary.md` 里的简历指标是否都能从 artifacts / code 里追溯？有没有夸大、混淆 deterministic harness、live model benchmark、module ablation 的地方？
6. 简历文案是否应该写 3 类模型后端，还是用户原始模板里的 2 类模型后端？请根据当前代码和 docs 判断。
7. 请列出必须修复的问题、建议修复的问题、以及可以保留为 benchmark signal 的失败项。
8. 最后给一个更准确的“完成定义”：如果让你接手，要做到哪一步才可以说这个 benchmark 工作真正完成？

请不要只做文字评价。请先读代码和文档，再给出带文件路径和证据的 review。输出用中文，结论先行。
```
