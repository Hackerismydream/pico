# AGENTS.md

Pico AI-collaboration spec. **Read this file before making any code change in this repo.**

Scope: Codex / Claude Code / Claude API / any AI-assisted work. When a rule here conflicts with an ad-hoc instruction in conversation, **this file wins** — unless the user *explicitly* says "ignore rule X in AGENTS.md".

Hard constraints only (violations get reverted / rejected). Soft suggestions and style preferences belong in personal notes or conversation, not here. See the [Maintenance](#maintenance) note before adding sections — shorter is better.

| # | Section | Gist |
|---|---|---|
| 1 | [Code comments](#1-code-comments) | Don't comment unless necessary; use the language clearest to readers |
| 2 | [Branch naming](#2-branch-naming) | `<type>/<snake_desc>`; confirm base before cutting |
| 3 | [Commits](#3-commits-conventional-commits) | Conventional Commits, all-English, `Co-authored-by` trailer |
| 4 | [Dependencies](#4-dependencies-uv-only) | `uv` only — never `pip` / hand-edit lockfile |
| 5 | [Tests](#5-tests) | `uv run pytest`; strict file-naming |
| 6 | [Domain terms](#6-domain-terms) | Consult `CONTEXT-MAP.md` before naming; use canonical terms |
| 7 | [Repository assets](#7-repository-assets) | No report assets, web artifacts, or large files in PRs |

---

## 1. Code comments

### §1.1 Top rule: don't add comments unless necessary

- Match the style of surrounding lines. If neighboring code has no comments, **don't** add one to your new line.
- Comment **only** when:
  - the logic is non-obvious;
  - there's a hidden constraint (e.g. call-order sensitivity, a caller must do X first);
  - you need to explain **why**, not **what** (the name already says what).
- **Don't** add comments that:
  - describe what the code does (`# Increment counter` next to `counter += 1`);
  - mark edits (`# ← new` / `# changed this line`);
  - reference a PR / Issue / locally-visible-only doc path (`# Refs: ...` — invisible to others);
  - describe transient task context (`# For the X bug` — stale once the task is done).

### §1.2 Comment language follows the audience

- Repository source comments may use any language. Choose the language that is
  clearest to the module's intended readers and keep neighboring comments
  consistent.
- Do not translate machine-readable directives, tool markers, protocol values,
  command examples, or third-party attribution merely for language consistency.

### §1.3 Examples

❌ Review annotation copied straight into source:

```python
self.logger = logger.bind(channel=self.name)   # ← new
```

❌ Neighbors have no comments, yet the new line adds a meaningless one:

```python
def __init__(self, config: Any, bus: MessageBus):
    self.config = config
    self.bus = bus
    self._running = False
    self.logger = logger.bind(channel=self.name)   # ← drop this comment
```

✅ Clean, no comment, consistent:

```python
def __init__(self, config: Any, bus: MessageBus):
    self.config = config
    self.bus = bus
    self._running = False
    self.logger = logger.bind(channel=self.name)
```

✅ Rare case that genuinely needs a *why*:

```python
# Bind channel name into logger context so every log entry auto-tags channel.
self.logger = logger.bind(channel=self.name)
```

### §1.4 Teaching modules: detailed Chinese comments allowed

Teaching modules are designated for onboarding and campus-recruitment training.
For these modules only, §1.1 (sparse comments) is relaxed.

- **Designation** — a module is a teaching module **only if** it appears in
  the teaching-module allowlist in `docs/plan/teaching-differentiation.md`
  **and** its module docstring's first line is `教学模块：`. CI checks
  allowlist–marker consistency, so the exemption cannot be self-declared.
  All other modules keep §1.1 / §1.2.
- **Language** — comments and docstrings in teaching modules are written in
  Simplified Chinese (the trainee audience is Chinese).
- **Required comment points**:
  - module docstring: 读者任务、职责、核心概念、数据流、入口类与函数、使用示例
  - class docstring: 职责、生命周期、与相邻模块的关系
  - public method: 参数、返回值、异常、边界行为
  - non-obvious logic: only **why**, not **what** — the §1.1 "what" bans still apply
  - teaching markers: `# 例：` / `# 为什么这里...`
- **Terminology** — Chinese terms must match the glossary in `CONTEXT.md`
  (中英对照); coining a new term requires adding it there in the same change.

---

## 2. Branch naming

### §2.1 Format

`<type>/<short-desc>`

| type | Use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Refactor (not a feature, not a bug fix) |
| `perf` | Performance |
| `chore` | Misc (deps bump, doc structure, etc.) |
| `docs` | Docs only |
| `test` | Tests only |

`short-desc`: **snake_case**, English, 3–5 words describing the change.

| ✅ Good | ❌ Bad |
|---|---|
| `feat/whatsapp_lid_mapping` | `feat/优化` |
| `fix/cron_dst_transition` | `bugfix` |
| `refactor/cli_cron_sentinel` | `huangjie-test` |
| `chore/upgrade_uv` | `tmp` |

### §2.2 Confirm the base before cutting

- Before cutting any branch (`fix` / `feat` / `refactor` / anything), **ask the user which base to cut from** — don't pick one silently.
- If unspecified, default to **`main`** (the integration branch).
- Flow: `git fetch origin main`, then cut from the latest tip.
- Combined with the branch-first rule: **confirm base + cut the branch, then start editing** — never write on a working branch and carve the branch out afterwards.

---

## 3. Commits (Conventional Commits)

### §3.1 Message format

```
<type>(<scope>): <subject>

<body — optional>

<footer — optional>
```

**type** — same set as §2.1, plus 3 commit-only types:

| type | Meaning |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Docs only |
| `refactor` | Refactor |
| `perf` | Performance |
| `test` | Tests only |
| `build` | Build system / external deps |
| `ci` | CI config |
| `chore` | Other misc |
| `revert` | Revert a prior commit |

**scope** — a top-level subpackage of `pico/` (for example, `cli`, `channels`, or `memory_engine`). Spanning multiple scopes → omit the scope, or use `(*)`.

**subject** — ≤ 72 chars; no trailing period; English. Sentence case and
lowercase starts are both accepted.

**footer** (optional):
- `BREAKING CHANGE: <desc>` — triggers a MAJOR bump once public;
- `Closes #123` — auto-closes the issue on merge.

### §3.1.1 Top rule: the whole message is English (subject + body + footer)

No other languages anywhere in the message — not just the subject; body and footer too.

| Part | Rule |
|---|---|
| subject | English, ≤ 72 chars, no period; uppercase or lowercase start |
| body | **All English**; when citing a non-English plan / discussion, **translate** it, don't paste |
| punctuation | **ASCII-only** — not just no full-width punctuation (`：`,`，`,`。`,`「」`,`""` …) but also no em-dash `—`, curly quotes, or ellipsis `…` (all non-ASCII, all rejected by CI); no `§`-numbering, no non-English path names; the latin part of a §N.M anchor is fine |
| trailer | `Co-authored-by: ...` is ASCII by format |

**Why:** Conventional-Commits tooling (commitlint / semantic-release / changelog generators) parses ASCII grammar and mis-lints on non-English text; cross-language reviewers and a public commit history both need English.

**Process:**
1. **Before writing:** translate the points in your head to English first — don't write a non-English body then translate (that leaves full-width residue).
2. **After writing:** self-check with `git log -1`; any non-English char → rewrite.
3. **Already committed but violating:** rewrite the message with `git rebase -i` **only after explicit user authorization**; don't rewrite history unprompted (see §3.4).

### §3.2 ✅ Good / ❌ Bad

✅ Good:

```
feat(cli): Rename cron show/remove to get/delete
fix(channels): Default allow_from to ['*'] instead of deny-all
refactor(cli): Replace --cron-expr with --cron and --every-seconds with --every
```

❌ Bad:
- `更新代码` (non-English + no type/scope);
- `update` (no type/scope);
- `feat: Cron 命令重命名为 get 和 delete.` (period + non-English).

### §3.3 Trailer rules (commit message + PR description)

**✅ Required:**

- `Co-authored-by: Claude (<model-id>) <noreply@anthropic.com>` — when Claude helped write the code, append it at the end of the commit body (blank line above), or at the end of the PR description.
  - `<model-id>` = the **actual current-session model ID** (e.g. `claude-opus-4-8` / `claude-sonnet-4-6` / `claude-haiku-4-5`), not a placeholder. The model version keeps per-model contribution distinguishable.
  - Format follows the aider convention; GitHub renders `Co-authored-by` as a co-author on the commit / PR.
- Multiple co-authors → one per line, standard git trailer format (`Name <email>`).
- The repo **squash-merges** PRs (rebase only freshens the branch before push; the merge collapses the branch to one commit on `main`). The squash commit's subject is the PR title and its body is the **PR description** (`squash_merge_commit_message=PR_BODY`) — individual commit bodies are dropped. GitHub still auto-collects each commit's `Co-authored-by` into the squash commit, so keep the trailer in your commit and put `Closes #NNN` + reviewer context in the PR description (that is what lands on `main`).

**❌ Don't add:**
- `Refs: ...` pointing at locally-visible-only / git-ignored paths (invisible to others);
- `🤖 Generated with Claude Code` and similar emoji banners — `Co-authored-by` already conveys co-authorship (and is the structured, machine-readable attribution); a marketing badge adds no attribution value;
- internal commit-hash references / temporary branch names — docs/PRs describe the present state only.

### §3.4 Hard rule: when to commit

- A request to implement, fix, finish, or continue through a named Issue or a
  bounded Issue range authorizes the commits required to complete that scope.
- Commit only complete, reviewed vertical slices. Do not commit after a
  read-only answer, diagnosis, or review unless the user also requests a change.
- A plan alone is not authorization. The user's execution request defines the
  authorized endpoint.
- **Don't** `git commit --amend` a prior commit (unless the user explicitly asks to amend).
- If a pre-commit hook fails, create a **new** commit to fix it — don't amend.

### §3.5 Sync before push + force-push boundary

**Rule:** before pushing a feature branch, base it on the **latest `main`**.

| Step | Command | Note |
|---|---|---|
| 1. Sync remote | `git fetch origin <target>` | Doesn't touch the working tree |
| 2. Dry-run conflicts | `git merge-tree --write-tree HEAD origin/<target>` | exit 0 = clean; non-zero prints conflicts |
| 3. Rebase (if remote ahead) | `git rebase origin/<target>` | Re-applies your branch onto the target tip |
| 4. Re-run tests | `uv run pytest <relevant tests> -x` | Confirm the rebase didn't break anything |
| 5. Push | `git push -u origin <branch>` (first) or `git push --force-with-lease` (after rebase) | — |

**Why:** CI runs "your commits on top of the latest remote" (catches runtime conflicts before merge) and the PR diff stays clean. Rebase here only freshens the branch base before push; the merge itself is a squash, which collapses the branch to a single commit on `main`.

**Force-push boundary:**
- ✅ `--force-with-lease` (checks the remote wasn't changed by others) on **your own feature branch** after a rebase;
- ❌ `git push --force` (blind, can clobber others' pushes);
- ❌ never force-push to long-lived / protected branches (`main`).

### §3.6 Hard rule: Agent push

- Always `git fetch` first to check ahead/behind;
- if the remote target has commits not on your branch, **rebase before pushing** (the §3.5 flow);
- **re-run tests after the rebase**;
- a user-authorized Issue or bounded Issue range authorizes pushes to its
  feature branches and PR landing on the private `origin`;
- never push to a remote outside the user-authorized target;
- use `--force-with-lease`, never `--force`.

### §3.7 After a successful push, self-review and land the PR

After pushing an authorized feature branch, self-review the complete diff,
create the PR with `gh pr create`, wait for required checks, and squash-merge it
without asking the user to judge routine commit, push, PR, or merge steps.

Stop for user input only when landing would materially exceed the authorized
Issue scope, require a destructive or irreversible external action, or leave a
high-impact review finding unresolved.

**Title:** same Conventional-Commits grammar as commits (`<type>(<scope>): <subject>`), subject reflecting the PR's overall goal, not any single commit. **Title length may relax to ≤ 90 chars** (the 72 limit is for `git log --oneline` wrapping; web-UI titles don't wrap) — but shorter is better.

**Description must be all English** (same as §3.1.1): no other languages / full-width punctuation / `§` numbering anywhere (subject + body + tables + checklist).

**Description structure: use the repo PR template** at `.github/pull_request_template.md` if present (`gh pr create` picks it up automatically); otherwise fill the structure below into `--body` by hand (all English):

```markdown
## Change description

> Description here

## Type of change
- [ ] Bug fix
- [ ] New feature
- [ ] Document
- [ ] Others

## Related issues (if there is)

> Fix [#1]()

## Checklists

### Development

- [ ] Lint rules pass locally
- [ ] Application changes have been tested thoroughly
- [ ] Automated tests covering modified code pass

### Security

- [ ] Security impact of change has been considered
- [ ] Code follows security best practices and guidelines

### Code review

- [ ] Pull request has a descriptive title and context useful to a reviewer. Screenshots or screencasts are attached as necessary
```

Filling rules:
- `Change description` — the PR's overall goal + key decisions (summarize the phase evolution for multi-commit PRs);
- `Type of change` — check what applies;
- check only the boxes you actually satisfied — leave the rest blank and explain in the description; never blanket-check;
- anything the template doesn't cover but the reviewer needs (breaking change / cherry-pick option / mixed topics) → append to `Change description`.

**Trailer** (with §3.3):
- squash-merge → GitHub auto-collects each commit's `Co-authored-by` into the squash commit, so keep the trailer in your commit and **don't add it to the PR description** (that duplicates it);
- `Closes #NNN` and reviewer context, by contrast, **must** live in the PR description — the squash commit body is taken from it (`squash_merge_commit_message=PR_BODY`), and individual commit bodies are dropped.

**Description must NOT contain** (same as §3.3):
- `🤖 Generated with [Claude Code](https://...)` marketing banners;
- `Refs: ...` to ignored/local-only paths;
- internal branch names / commit-hash references (no reviewer context).

**Preview-verification (required):**
1. After drafting, **grep for any non-ASCII char first** (the CI lints the whole message as ASCII-only via `commit_lint._is_ascii`, and the squash commit body is this PR description — so it must be ASCII too):
   ```bash
   grep -nP "[^\x00-\x7F]" /tmp/pr_description.md
   # must print nothing (0 matches). Catches em-dash/curly-quotes/ellipsis,
   # not just CJK + full-width — a CJK-only pattern gives a false pass.
   ```
2. review the full title and body against the Issue, diff, verification evidence,
   and PR template;
3. run `gh pr create --title "..." --body "$(cat /tmp/pr_description.md)"`;
4. report the PR URL and final merge status.

**Not allowed:**
- pushing and walking away, leaving PR creation to the user;
- creating a PR description without checking for non-English residue;
- landing a PR with unresolved required checks or unresolved high-impact review
  findings.

---

## 4. Dependencies (uv only)

### §4.1 `uv` is the only Python package manager

| Action | Command |
|---|---|
| Add runtime dep | `uv add <package>` |
| Add dev dep | `uv add --dev <package>` |
| Remove dep | `uv remove <package>` |
| Sync env from lockfile | `uv sync` |
| Upgrade one package | `uv lock --upgrade-package <package>` |
| Upgrade all | `uv lock --upgrade` |
| Run a command in the project env | `uv run <command>` |

### §4.2 Forbidden

- ❌ `pip install` / `pip uninstall`;
- ❌ hand-editing `[project.dependencies]` / `[project.optional-dependencies]` / `[dependency-groups]` in `pyproject.toml`;
- ❌ hand-editing `uv.lock`;
- ❌ `pip freeze > requirements.txt`;
- ❌ `python -m pip install ...` to bypass uv.

### §4.3 Exception

If the user *explicitly* says "let me try pip" / "manually add this line to pyproject", follow the user. This rule constrains Claude's **default** behavior, not the user's direct instructions.

---

## 5. Tests

### §5.1 Unit tests

Under `tests/test_*.py`. CLI unit tests use one shape:

```
tests/test_cli_<module>_commands.py
```

- one file per module (aligns with `pico/cli/<module>_commands.py`);
- **don't** split by phase / feature / ticket (no `phase4` / `eve151` suffixes);
- aspect suffixes are allowed:
  - testing a CLI private helper: `test_cli_<helper>.py` (e.g. `test_cli_helpers.py` / `test_cli_stacks.py`);
  - cross-module behavior: `test_cli_<aspect>.py` (e.g. `test_cli_config_precedence.py` / `test_cli_smoke.py`).

### §5.2 Integration tests

Under `tests/integration/test_*.py`. Run against real environments (real LLM / channel / fcntl / subprocess / VM, etc.).

Naming: `test_<scope>_<kind>.py`, where `<kind>` ∈:

| kind | Meaning |
|---|---|
| `e2e` | End-to-end happy path, single/multi module |
| `smoke` | Multi-module interplay, just "it runs" |
| `real_<resource>` | Hits a real resource (`real_vm` / `real_llm` / `real_channel`, …) |

- **`<scope>` must not carry a version / ticket number** (no `v002` / `eve151`) — use a feature/scenario description.

### §5.3 Examples

| ❌ Wrong | ✅ Right | Reason |
|---|---|---|
| `test_cli_cron.py` | `test_cli_cron_commands.py` | missing `_commands` suffix |
| `test_gateway_cli.py` | `test_cli_gateway_commands.py` | order reversed |
| `test_cli_gateway_phase4.py` | merge into `test_cli_gateway_commands.py` | no phase suffix |
| `tests/integration/test_v002_smoke.py` | `test_<feature>_smoke.py` | no version number |
| `tests/integration/test_eve151_smoke.py` | `test_<feature>_smoke.py` | no ticket number |

### §5.4 Hard rules for Claude

- when changing/adding a CLI command, update the matching `test_cli_<module>_commands.py` — **don't create a new file**;
- when you spot a legacy file violating §5.1 / §5.2, **report it to the user first** — don't rename it unprompted (renames touch git history and may collide with follow-up PRs);
- always run tests via `uv run pytest ...`, never bare `pytest` (per §4).

---

## 6. Domain terms

- Naming a domain concept tracked in `CONTEXT-MAP.md` (the entry point — it routes to `CONTEXT.md` for Runtime terms and `ui-tui/CONTEXT.md` for TUI)? Use the canonical term, not a synonym.
- Coining a new domain term: define it in the matching `CONTEXT.md` in the same change, with a definition verifiable against the code (not guessed) — add an `_Avoid_` list only if a confusable synonym exists.

---

## 7. Repository assets

- Do not commit report assets or standalone web artifacts, regardless of size. This includes images, GIFs, SVGs, videos, audio files, PDFs, HTML files, web manifests, and WASM bundles.
- Store public-report assets outside git and link to them when needed.
- Do not add or modify files over 1 MiB unless the maintainer explicitly approves it before the commit.
- Run `make check-large-files` when touching docs, demos, reports, assets, or generated outputs; CI enforces the same rule on added and modified PR files.

---

## Maintenance

This file holds **hard constraints only** (rules whose violation gets reverted / rejected). Soft suggestions, design preferences, and style leanings go in personal notes or conversation — not here.

Before adding a section, confirm with the user in conversation first — the shorter AGENTS.md stays, the more useful it is.
