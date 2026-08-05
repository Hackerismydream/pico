# Pico reference Skills

This source directory holds package-reference Skills. Each Skill is a directory
containing `SKILL.md` with YAML frontmatter and agent instructions.

The current source checkout discovers this directory. The `0.1.7` wheel
allowlist does not yet guarantee these files are included, so do not treat the
weather Skill as an installed-wheel contract until V-P0 protects it.

## Available Skills

| Skill | Description |
|-------|-------------|
| `weather` | Get current weather and forecasts (wttr.in + Open-Meteo, no API key) |

## Notes

User-defined Skills can be placed under `<workspace>/skills/` or a directory
listed in `skill_forge.local_dirs`. Workspace Skills take precedence over
configured directories and package-reference Skills.
