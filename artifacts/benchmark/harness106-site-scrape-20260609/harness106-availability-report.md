# Harness-Bench 106-task Website Availability Report

## Scope
- Source site: https://www.harness-bench.ai/domains.html
- Branch/worktree: `codex/v3-harness106-reconstruction` at `/Users/martinlos/code/pico-v3-harness106-reconstruction`
- Baseline: `v3` at commit `47a055e`
- Scrape artifact: `artifacts/benchmark/harness106-site-scrape-20260609/`

## What is publicly visible on the website
- 8 domain pages.
- 106 task pages.
- Each task page exposes task metadata, prompt text, LLM rubric, and completion grader text.
- 28 task pages also expose hook code blocks.
- 509 input file download links are listed across the 106 task pages.

## Download link check
- Input file links checked: 509
- HTTP 200: 1
- HTTP 404: 508
- Missing download list: `missing_downloads.txt`
- URL status artifact: `download_url_status.json`

The only successful fixture download was:

```text
001-file in/input.txt
https://raw.githubusercontent.com/Qihoo360/harness-bench/refs/heads/main/tasks/01-file/fixtures/in/input.txt
```

Representative missing fixture links:

```text
016-code-repair-pytest in/app/config_manager.py
https://raw.githubusercontent.com/Qihoo360/harness-bench/refs/heads/main/tasks/016-code-repair-pytest/fixtures/in/app/config_manager.py

106-release-approval-gate-plan ...
https://raw.githubusercontent.com/Qihoo360/harness-bench/refs/heads/main/tasks/106-release-approval-gate-plan/...
```

## GitHub repository check
The official GitHub repository currently fetched locally as:

```text
origin https://github.com/Qihoo360/harness-bench.git
origin/main 8d31d6c initial commit
```

The local official checkout exposes 28 task directories, not 106.

## Conclusion
The website is enough to build a 106-task catalog and partial skeleton, but it is not enough to run the official 106-task benchmark locally.

A runnable Harness-Bench task needs at least:

- `task.yaml`
- `prompt.txt`
- complete `fixtures/`
- hook module when needed
- oracle grader module
- optional LLM rubric

The website exposes prompt/rubric/grader text in HTML, but the fixture file contents are mostly unavailable because the raw GitHub download links return 404. Without the fixtures, the oracle graders cannot evaluate real workspaces and the benchmark cannot be run honestly.

## Correct statement
Can say:

> We scraped the public Harness-Bench website and verified that it lists 106 tasks, but the public fixture downloads are unavailable for 508/509 linked input files. Therefore the website does not currently provide a complete runnable 106-task benchmark package.

Cannot say:

> Pico v3 completed the official 106-task Harness-Bench benchmark.

## Next requirement
To run the true 106-task benchmark, we need the official complete task package or a repository/archive that includes the missing fixture files and task modules.
