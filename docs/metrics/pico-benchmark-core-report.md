# Pico Benchmark Core Report

这轮 benchmark 只收缩到 Harness regression、context ablation、context efficiency、memory fidelity、memory agent evaluation 和 recovery ablation，不把 provider、run aggregation 或 live-provider 结论揉进来。

## Harness Regression
- 固定 regression 任务数：12
- pass_rate：100.00%
- within_budget_rate：100.00%
- verifier_pass_rate：100.00%

## Context Ablation
- 配置数：12
- avg_full_prompt_chars：5663.67
- avg_raw_prompt_chars：7082.33
- avg_prompt_compression_ratio：16.19%
- max_prompt_compression_ratio：33.28%
- current_request_preserved_rate：100.00%

## Context Efficiency Under Follow-up
- memory_on repeated_reads：0
- memory_off repeated_reads：60
- memory_on avg_tool_steps：0.00
- memory_on correct_rate：100.00%
- memory_hit_rate：100.00%

## Memory Fidelity
- pass_rate：100.00%
- irrelevant_injection_rate：0.00%
- supersede_success_rate：100.00%
- secret_exposure_rate：0.00%
- stale_detection_rate：100.00%
- stale_use_rate：0.00%
- poison_quarantine_rate：100.00%
- benign_recall_retention_rate：100.00%

## Dream Quality
- signal_retention_rate：100.00%
- noise_rejection_rate：100.00%
- secret_rejection_rate：100.00%
- dedupe_rate：100.00%
- relative_date_absolutization_rate：100.00%

## Memory Contract Verification
- total_cases：8
- passed：8
- failed：0
- pass_rate：100.00%

## Memory Challenge Benchmark
- case_count：55
- variants：memory_off, memory_on, naive_recent, unsafe_memory
- memory_on answer_accuracy：94.55%
- memory_on case_pass_rate：94.55%
- memory_on failed：3
- memory_on evidence_recall_at_k：100.00%
- memory_on evidence_precision_at_k：87.23%
- memory_on stale_use_rate：0.00%
- memory_on secret_exposure_rate：0.00%
- memory_on false_resume_accept_rate：0.00%
- memory_off answer_accuracy：41.82%
- unsafe_memory secret_exposure_rate：100.00%
- memory_on_vs_memory_off evidence_recall_delta：100.00%
- memory_on_vs_memory_off repeated_reads_reduction：0.58
- memory_on_vs_unsafe_memory secret_exposure_reduction：100.00%

## Recovery / Resume Ablation
- resume_success_rate：90.00%
- stale_reanchor_rate：100.00%
- workspace_drift_detection_rate：100.00%
- resume_false_accept_rate：0.00%
- resumption_success_rate：100.00%
- first_action_correctness：100.00%
- todo_continuity_rate：100.00%

## 可以安全写进简历的指标
- avg_full_prompt_chars
- avg_raw_prompt_chars
- avg_prompt_compression_ratio
- max_prompt_compression_ratio
- repeated_reads
- avg_tool_steps
- correct_rate
- evidence_recall_at_k
- evidence_precision_at_k
- task_correctness_rate
- stale_memory_use_rate
- secret_exposure_rate
- resume_success_rate
- workspace_drift_detection_rate
- resume_false_accept_rate

## 只适合放文档/面试展开的指标
- current_request_preserved_rate
- memory_hit_rate
  - scripted variant 下与 `repeated_reads == 0` tautological
- stale_reanchor_rate
- failure_category_counts

## 口径边界
- Harness regression 只证明 runtime 合同稳定，不证明 provider 上限。
- Context、memory、recovery 这三层只证明模块收益，不和 provider benchmark 混写。
