# PicoBench Live / Dogfood

This directory is a public skeleton for live and dogfood task manifests. It is
not the hidden task store.

Live tasks are for contamination-resistant evaluation. A task should enter this
track only after it has:

- a base commit or fixture digest;
- a user-style prompt with secrets removed;
- public setup instructions;
- hidden fail-to-pass tests stored outside the public repo;
- three stability runs with the same verifier result;
- a task-quality note for clarity, coverage, effort, and risk.

Do not publish hidden tests, private repos, credentials, or raw user logs here.
