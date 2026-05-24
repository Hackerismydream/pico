# PicoBench Hidden Test Rationale v0.3

| Task | Hidden Edge | Is It Implied By Task Contract? | Rationale | Decision |
|---|---|---:|---|---|
| `core_016` | Numeric strings in JSON filter should be accepted where numeric values are accepted | 1 | Filtering user JSON commonly receives string-encoded numbers; the public contract says JSON filtering, not Python-only numeric object filtering | keep as signal |
| `core_018` | Todo item text should trim extra whitespace | 1 | The parser task is about normalized todo items; preserving incidental indentation leaks source formatting into semantic item text | keep as signal |
| `core_019` | Empty URL path should not force an extra trailing slash | 1 | URL joining should preserve canonical base URL semantics; empty path is a no-op, not a request for slash mutation | keep as signal |
| `core_023` | `None` table cells render as empty cells | 1 | Markdown table formatting should treat missing cell values as empty output rather than Python repr text | keep as signal |
| `core_027` | No-frontmatter fallback and empty tag filtering | 1 | The renderer/parser task requires robust document handling; no-frontmatter docs and empty tags are normal content edges | keep as signal |
| `core_028` | Blank-token audit should not over-redact | 1 | Secret redaction should remove real secrets without fabricating redaction markers when no token exists | keep as signal |
| `core_030` | Implicit dependency-only nodes are valid graph nodes, not cycles | 1 | A scheduler DAG must tolerate nodes introduced only through dependency references; cycle detection should not confuse implicit nodes with cycles | keep as signal, mark stability-sensitive |
| `core_032` | Empty check list should produce `failed` plus `0/0 checks passed` | 1 | A report manifest with zero checks should not be treated as passed; the summary string makes the empty input explicit for auditability | keep as signal |
