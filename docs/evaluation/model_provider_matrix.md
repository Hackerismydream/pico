# PicoBench Model Provider Matrix

| Provider | Protocol | Model | Base URL source | Key source | CI allowed | Manual live allowed | Notes |
|---|---|---|---|---|---|---|---|
| `deepseek` | `anthropic` | `DEEPSEEK_MODEL` or `PICO_DEEPSEEK_MODEL`, default `deepseek-v4-pro` | `DEEPSEEK_API_BASE`, `DEEPSEEK_BASE_URL`, or `PICO_DEEPSEEK_API_BASE` | `DEEPSEEK_API_KEY` or `PICO_DEEPSEEK_API_KEY` | No | Yes | Current Phase 3 smoke provider |
| `openai` | `openai` | `OPENAI_MODEL` or `PICO_OPENAI_MODEL` | `OPENAI_API_BASE`, `OPENAI_BASE_URL`, or `PICO_OPENAI_API_BASE` | `OPENAI_API_KEY` or `PICO_OPENAI_API_KEY` | No | Yes | Not used by default live smoke |
| `anthropic` | `anthropic` | `ANTHROPIC_MODEL` or `PICO_ANTHROPIC_MODEL` | `ANTHROPIC_API_BASE`, `ANTHROPIC_BASE_URL`, or `PICO_ANTHROPIC_API_BASE` | `ANTHROPIC_API_KEY` or `PICO_ANTHROPIC_API_KEY` | No | Yes | Also covers right.codes compatible profiles |

Do not record raw keys in repo files, CI logs, workflow inputs, or benchmark
artifacts.
