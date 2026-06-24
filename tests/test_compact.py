from pico.core.compact import CompactManager


def summary_text(items):
    return CompactManager(agent=None)._summary_text(items)


def test_compact_summary_preserves_early_user_constraints():
    summary = summary_text(
        [
            {
                "role": "user",
                "content": "先看实现。不要改公共 API。最后用中文说明。",
            },
            {
                "role": "assistant",
                "content": "选择保留现有入口，因为外部调用依赖它。",
            },
            {
                "role": "tool",
                "name": "read_file",
                "args": {"path": "pico/core/compact.py"},
                "content": "class CompactManager: ...",
            },
            {
                "role": "user",
                "content": "继续修 compact 摘要。",
            },
        ]
    )

    assert "- Goal: 继续修 compact 摘要。" in summary
    assert "- User constraints: 不要改公共 API" in summary
    assert "- Key decisions: 选择保留现有入口" in summary
    assert "- Files read: pico/core/compact.py" in summary


def test_compact_summary_uses_dash_for_missing_structured_fields():
    summary = summary_text(
        [
            {"role": "user", "content": "看一下 compact。"},
            {"role": "assistant", "content": "我先阅读相关文件。"},
            {
                "role": "tool",
                "name": "read_file",
                "args": {"path": "pico/core/context_manager.py"},
                "content": "ok",
            },
        ]
    )

    assert "- User constraints: -" in summary
    assert "- Key decisions: -" in summary
    assert "- Rejected paths: -" in summary
    assert "- Last error context: -" in summary
    assert "- Critical artifacts: -" in summary


def test_compact_summary_extracts_bilingual_constraints_errors_and_artifacts():
    summary = summary_text(
        [
            {
                "role": "user",
                "content": "Don't change public API. 必须保持 session JSON schema。",
            },
            {
                "role": "assistant",
                "content": (
                    "Tried regex-only extraction but it doesn't work. "
                    "We decided to keep deterministic compact instead."
                ),
            },
            {
                "role": "tool",
                "name": "patch_file",
                "args": {"path": "pico/core/compact.py"},
                "content": "patched",
                "artifact_ref": "artifact://tool/patch-1",
            },
            {
                "role": "tool",
                "name": "shell",
                "content": (
                    "FAILED tests/test_compact.py::test_summary "
                    "AssertionError: expected input_tokens"
                ),
                "artifact_ref": "artifact://tool/test-1",
            },
        ]
    )

    assert "Don't change public API" in summary
    assert "必须保持 session JSON schema" in summary
    assert "We decided to keep deterministic compact instead" in summary
    assert "Tried regex-only extraction but it doesn't work" in summary
    assert "- Last error context: FAILED tests/test_compact.py::test_summary" in summary
    assert "- Files modified: pico/core/compact.py" in summary
    assert "artifact://tool/patch-1" in summary
    assert "artifact://tool/test-1" in summary


def test_compact_summary_splits_constraints_on_newlines_and_tracks_didnt_work():
    summary = summary_text(
        [
            {
                "role": "user",
                "content": "修复上下文问题\nonly touch compact internals",
            },
            {
                "role": "assistant",
                "content": "Tried stateful parsing but it didn't work, reverted to stateless rules.",
            },
        ]
    )

    assert "only touch compact internals" in summary
    assert "Tried stateful parsing but it didn't work" in summary


def test_compact_summary_is_capped_at_2000_chars():
    summary = summary_text(
        [
            {
                "role": "user",
                "content": "必须保留这些约束。" + "x" * 5000,
            },
            {
                "role": "tool",
                "name": "shell",
                "content": "Traceback " + "y" * 5000,
            },
        ]
    )

    assert len(summary) <= 2000
