# M0 Baseline Audit (Pre-M0 C0)

Baseline for `Pico Memory Eval Roadmap v2`.

- Repo: `/Users/martinlos/code/pico`
- Base branch: `v3`
- Base commit: `d46026647905174f806122db5262dfddb3517fc6`
- Audit branch: `codex/memory-eval-roadmap-v2-m0`
- Plan: `_local/benchmark/artifacts/plans/memory_eval_roadmap.md`
- Scope: read-only audit for Appendix A; no business-code changes.

## Plan Constraints Confirmed

Read the full roadmap before making this file. The constraints that govern the next commits are:

- Filesystem-first memory only.
- No vector DB or embedding store.
- No live provider before M5.
- Do not refactor `LayeredMemory` or `DurableMemoryStore` main storage backend; sidecar files are allowed.
- Do not change existing artifact bytes for `memory-ablation-v2.json`, `context-ablation-v2.json`, `recovery-ablation-v2.json`, or `harness-regression-v2.json`.
- Do not rename existing anchors: `run_large_scale_memory_experiment`, `run_memory_ablation_v2`, `write_benchmark_core_report`, `LayeredMemory`, `DurableMemoryStore.promote`, `retrieval_view`, `invalidate_stale_file_summaries`.
- Do not change `retrieval_view` signature; Pre-M0 C2 must add `retrieval_view_structured` and keep the string view compatible.
- Schema policy: append fields by default; bump `schema_version` only for reader-incompatible changes.
- M2 and M4 must not bump schema versions.
- Explicitly out of scope: `valid_from`, `valid_until`, `polarity`, `source_freshness`, single `memory_score`, `.dream-runs/` staging, MemoryArena/STATE-Bench full reproduction.

The working tree had pre-existing untracked files before this audit (`.gitee/`, `.gstack/`, `examples/`, and two `release/v3/learning/assets/10-local-code-agent-harness.*` files). This audit does not touch or stage them.

## 1. Metadata Field Collision Check

Command:

```bash
grep -rn "status\|supersedes\|evidence\|scope" pico/features/memory.py
```

Current hits:

```text
pico/features/memory.py:424:- Deleting contradicted facts; if current evidence disproves an old memory, fix it at the source.
pico/features/memory.py:511:        memory_scope = Path(agent.memory_dir).resolve().relative_to(agent.root)
pico/features/memory.py:513:        memory_scope = Path(".pico") / "memory"
pico/features/memory.py:523:        write_scope=[str(memory_scope)],
pico/features/memory.py:575:    audit["auto_dream"]["status"] = "submitted"
pico/features/memory.py:576:    started_payload = {"session_ids": session_ids, "session_count": len(session_ids), "status": "submitted"}
pico/features/memory.py:583:            audit["auto_dream"]["status"] = "finished"
pico/features/memory.py:588:            audit["auto_dream"]["status"] = "failed"
```

Finding: the planned sidecar fields `status`, `supersedes`, `evidence`, and `scope` do not currently exist as durable note metadata fields. Existing `status` usage belongs to auto-dream audit state; existing `scope` usage is sandbox write scope.

## 2. Current Memory Injection Points

Command:

```bash
grep -rn "memory\|retrieval_view\|relevant_memory\|Memory" pico/core/context_manager.py
```

Relevant injection points:

```text
pico/core/context_manager.py:103:        memory_text = "Memory:\n- disabled" if not memory_enabled else str(self.agent.memory_text())
pico/core/context_manager.py:112:            section_texts["memory"] += "\n\n" + self.agent.todo_ledger.render_prompt()
pico/core/context_manager.py:117:            section_texts["memory"] += "\n\n" + checkpoint_text
pico/core/context_manager.py:119:            section_texts["memory"] += "\n\n" + memorylib.build_memory_system_section(self.agent.memory_dir)
pico/core/context_manager.py:121:        if memory_enabled and relevant_memory_enabled and hasattr(self.agent, "memory") and hasattr(self.agent.memory, "retrieval_candidates"):
pico/core/context_manager.py:122:            selected_notes = self.agent.memory.retrieval_candidates(user_message, limit=RELEVANT_MEMORY_LIMIT)
pico/core/context_manager.py:185:    def _render_sections_without_reduction(self, section_texts, selected_notes=None):
pico/core/context_manager.py:187:        relevant_lines = ["Relevant memory:"]
pico/core/context_manager.py:189:            relevant_lines.extend(f"- {note['text']}" for note in selected_notes)
pico/core/context_manager.py:235:            elif section == "relevant_memory":
pico/core/context_manager.py:236:                rendered[section] = self._render_relevant_memory(selected_notes or [], int(budget or 0))
pico/core/context_manager.py:245:    def _render_relevant_memory(self, selected_notes, budget):
pico/core/context_manager.py:247:        note_texts = [str(note.get("text", "")) for note in selected_notes if str(note.get("text", "")).strip()]
pico/core/context_manager.py:356:            "relevant_memory": {
pico/core/context_manager.py:359:                "selected_notes": [note["text"] for note in selected_notes],
pico/core/context_manager.py:360:                "selected_sources": [str(note.get("source", "")).strip() for note in selected_notes],
pico/core/context_manager.py:361:                "selected_kinds": [str(note.get("kind", "episodic")).strip() or "episodic" for note in selected_notes],
```

Finding: `context_manager.py` currently injects only selected notes into prompt sections. It does not call `retrieval_view`; it calls `agent.memory.retrieval_candidates(...)`. Pre-M0 C6 must keep rejected notes out of this file's prompt path.

## 3. Existing Trace Event Surface

Command:

```bash
grep -rn "emit_trace\|trace_event\|emit(" pico/core/
```

Implementation surface:

```text
pico/core/runtime.py:715:    def emit_trace(self, task_state, event, payload=None):
pico/core/session_events.py:20:    def emit(self, event, payload=None):
```

Source-level `emit_trace` call sites, excluding `__pycache__` binary matches:

```text
pico/core/engine_helpers.py:70:    agent.emit_trace(
pico/core/engine_helpers.py:85:    agent.emit_trace(
pico/core/engine_helpers.py:131:        agent.emit_trace(
pico/core/engine_helpers.py:140:    agent.emit_trace(
pico/core/turn_transitions.py:80:    return agent.emit_trace(task_state, "loop_transition", payload)
pico/core/compact.py:39:            self.agent.emit_trace(self.agent.current_task_state, "compaction_started", {"trigger": trigger, "pre_tokens": summary["pre_tokens"]})
pico/core/compact.py:40:            self.agent.emit_trace(self.agent.current_task_state, "compaction_finished", summary)
pico/core/completion_governance.py:20:        agent.emit_trace(task_state, "before_final_hook_decision", hook_decision)
pico/core/completion_governance.py:41:    agent.emit_trace(task_state, "final_readiness_decision", decision)
pico/core/completion_governance.py:159:    agent.emit_trace(
pico/core/completion_governance.py:165:    agent.emit_trace(
pico/core/completion_governance.py:215:        agent.emit_trace(
pico/core/engine.py:106:        agent.emit_trace(
pico/core/engine.py:138:            agent.emit_trace(
pico/core/engine.py:151:                agent.emit_trace(
pico/core/engine.py:163:                agent.emit_trace(
pico/core/engine.py:176:                agent.emit_trace(
pico/core/engine.py:189:                agent.emit_trace(
pico/core/engine.py:197:            agent.emit_trace(
pico/core/engine.py:259:                    agent.emit_trace(
pico/core/engine.py:304:            agent.emit_trace(
pico/core/model_errors.py:31:    agent.emit_trace(
pico/core/model_errors.py:50:    agent.emit_trace(
pico/core/model_errors.py:55:    agent.emit_trace(
pico/core/governance.py:27:    return agent.emit_trace(
```

Trace event names confirmed from the call sites:

- `tool_executed`
- `checkpoint_created`
- `step_limit_summary_failed`
- `step_limit_summary`
- `loop_transition`
- `compaction_started`
- `compaction_finished`
- `before_final_hook_decision`
- `final_readiness_decision`
- `run_finished`
- `memory_maintenance_failed`
- `run_started`
- `prompt_built`
- `runtime_identity_mismatch`
- `model_requested`
- `model_retry_scheduled`
- `model_parsed`
- `model_error`
- `governance_decision`

Session event bus events confirmed in the same surface include:

- `user_message`
- `assistant_message`
- `model_requested`
- `model_retry_scheduled`
- `model_parsed`
- `model_error`
- `turn_finished`
- `context_usage_recorded`
- `memory_maintenance_failed`
- `todo_changed`
- `compaction_created`

Finding: the runtime trace API to use for Pre-M0 C6 is `agent.emit_trace(task_state, event, payload)`. There is no current `memory.retrieval` event.

## 4. Existing Artifact Types

Command:

```bash
grep -rn '"artifact_type"' pico/evaluation/ _local/benchmark/artifacts/
```

Current hits:

```text
pico/evaluation/metrics.py:1550:        "artifact_type": "context-ablation-v2",
pico/evaluation/metrics.py:1563:        "artifact_type": "memory-ablation-v2",
pico/evaluation/metrics.py:1583:        "artifact_type": "recovery-ablation-v2",
_local/benchmark/artifacts/recovery-ablation-v2.json:2:  "artifact_type": "recovery-ablation-v2",
_local/benchmark/artifacts/plans/memory_eval_roadmap.md:501:4. 现有 artifact_type 清单：`grep -rn '"artifact_type"' pico/evaluation/ _local/benchmark/artifacts/`
_local/benchmark/artifacts/memory-ablation-v2.json:2:  "artifact_type": "memory-ablation-v2",
_local/benchmark/artifacts/context-ablation-v2.json:2:  "artifact_type": "context-ablation-v2",
```

Additional artifact file present but without an `artifact_type` key:

```text
_local/benchmark/artifacts/harness-regression-v2.json
```

Finding: the existing `artifact_type` keys are `context-ablation-v2`, `memory-ablation-v2`, and `recovery-ablation-v2`. `harness-regression-v2.json` exists but does not currently declare `artifact_type`.

## 5. Current `retrieval_view` Call Points

Command:

```bash
grep -rn "retrieval_view" pico/ tests/
```

Current source/test hits:

```text
pico/features/memory.py:1117:def retrieval_view(state, query, limit=3, workspace_root=None):
pico/features/memory.py:1214:    def retrieval_view(self, query, limit=3):
pico/features/memory.py:1215:        return retrieval_view(self.state, query, limit=limit, workspace_root=self.workspace_root)
tests/test_context_manager.py:123:    agent.memory.retrieval_view = lambda query, limit=3: "Relevant memory:\n" + "\n".join(f"- {i} " + ("C" * 220) for i in range(5))
tests/test_memory.py:56:    lines = [line for line in memory.retrieval_view("recall memory", limit=4).splitlines() if line.startswith("- ")]
tests/test_memory.py:135:    lines = [line for line in memory.retrieval_view("constrained tools", limit=4).splitlines() if line.startswith("- ")]
```

Finding: the plan's caller list is accurate. `retrieval_view` is not used by `context_manager.py`; current prompt injection uses `retrieval_candidates`.

## 6. Current Durable Topic Markdown Format

Relevant code:

```text
pico/features/memory.py:738:    def _write_topic(self, topic, notes):
pico/features/memory.py:741:        lines = [
pico/features/memory.py:742:            f"# {meta['title']}",
pico/features/memory.py:744:            f"- topic: {topic}",
pico/features/memory.py:745:            f"- summary: {meta['summary']}",
pico/features/memory.py:746:            f"- tags: {', '.join(meta['tags'])}",
pico/features/memory.py:747:            f"- updated_at: {now()}",
pico/features/memory.py:749:            "## Notes",
pico/features/memory.py:751:        for note in notes:
pico/features/memory.py:752:            lines.append(f"- {note}")
```

Current topic sample from `.pico/memory/topics/project-conventions.md`:

```markdown
# Project Conventions

- topic: project-conventions
- summary: Stable repository conventions and defaults.
- tags: convention
- updated_at: 2026-04-12T08:14:49.837537+00:00

## Notes
- Use constrained tools instead of guessing.
- Preserve local agent state under .pico/.
```

Current topic sample from `.pico/memory/topics/key-decisions.md`:

```markdown
# Key Decisions

- topic: key-decisions
- summary: Long-lived decisions and rationale anchors.
- tags: decision
- updated_at: 2026-06-08

## Runtime scaling (2026-05-12)

- Before pico release: max_steps raised from 6 to 30 to match cc-mini ergonomics.
- max_new_tokens changed from hardcoded 512 to per-provider inference: DeepSeek 8192, Anthropic 32000.
- total_budget raised from 12000 to 60000 so prompts are no longer squeezed for 512-token models.
- These changes also fixed the historical auto-dream empty_response failure root cause.

## Differentiation from cc-mini (2026-05-12)

- Public release targets cc-mini as reference, but pico keeps unique selling points:
  - Context budget with workspace fingerprinting
  - runs/ checkpoints
  - memory + auto-dream as a resume/continuity feature

## Memory architecture

- Keep durable memory topic-based and lightweight.
- auto-dream runs in background to consolidate logs into topic files.
```

Current sidecar state:

```text
find .pico/memory/topics -maxdepth 1 -name '*.metadata.jsonl' -print
# no output
```

Finding: topic markdown files are the only durable topic storage today. No `*.metadata.jsonl` sidecars exist yet. `load_topic_notes` only captures bullets after an exact `## Notes` heading; the current `key-decisions.md` sample contains other headings and would not yield those bullets through `load_topic_notes`.

## 7. CLI Resume Support

Command:

```bash
grep -n "resume" pico/cli.py
```

Current hits:

```text
pico/cli.py:172:    session_id = args.resume
pico/cli.py:283:        "--resume", default=None, help="Session id to resume or 'latest'."
pico/cli.py:438:    if user_input.startswith("/resume "):
pico/cli.py:443:        agent.resume_session(session_id)
pico/cli.py:444:        return True, False, f"resumed session {session_id}"
pico/cli.py:497:            f"resume status: {agent.resume_state.get('status', '-')}",
```

Relevant snippets:

```text
pico/cli.py:172:    session_id = args.resume
pico/cli.py:173:    if session_id == "latest":
pico/cli.py:174:        session_id = store.latest()
pico/cli.py:283:        "--resume", default=None, help="Session id to resume or 'latest'."
pico/cli.py:438:    if user_input.startswith("/resume "):
pico/cli.py:440:        session_id = _resolve_session_id(agent, target.strip())
pico/cli.py:443:        agent.resume_session(session_id)
```

Finding: CLI supports `--resume <id>` and `--resume latest`; REPL supports `/resume <id-or-alias>`.

## Baseline Notes for Pre-M0 C1-C7

- C1 can add a metrics CLI without changing existing artifact files.
- C2 must bridge two retrieval paths: the string `retrieval_view` path and the prompt path currently using `retrieval_candidates`.
- C3 sidecar metadata has no durable-note field conflict, but must preserve existing `topics/*.md` bytes on first-load migration.
- C4/C5 helper names do not currently exist in `memory.py`.
- C6 should emit through `agent.emit_trace(...)`; the exact runtime call site must be selected from the current prompt-building path.
- C7 should add a new module; no current `memory_lint.py` exists.
