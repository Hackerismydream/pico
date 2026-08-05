# Changelog

All notable Pico changes are documented here.

## Unreleased

### Changed

- Unified the Pico product, CLI, Python package, configuration, and state
  identity.
- Focused one shared Runtime on CLI, TUI, Gateway, Cron, Subagents, and the
  Feishu, QQ, and WeCom Channels.
- Selected CodeCairn as the repository-scoped Memory backend through the public
  Plugin interface.
- Kept Evolver candidate generation opt-in, evidence-gated, manually activated,
  and rollback-aware.

### Removed

- Removed messaging Channels outside the supported Feishu, QQ, and WeCom set.
- Removed proactive Sentinel behavior, media generation, Deep Research,
  MiroThinker, and remote Skill marketplace behavior.
- Removed compatibility namespaces, implicit state migration, and bundled
  Memory implementations outside the installed Plugin contract.
