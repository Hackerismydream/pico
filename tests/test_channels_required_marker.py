"""Guard: channel ``required`` markers stay aligned with adapter ``start()`` guards.

Each channel's required set below is the audited truth — the credentials whose
absence makes the adapter bail on startup (see the referenced guard). The schema
markers (``Field(json_schema_extra={"required": True})``) must match this table
exactly. When an adapter changes what it enforces, update the adapter, the schema
marker, and this table in the same change.
"""

from __future__ import annotations

import pytest

from pico.config.update_channels import channel_field_specs

# channel -> required fields, each backed by the adapter guard that proves it.
EXPECTED_REQUIRED: dict[str, set[str]] = {
    "feishu": {"app_id", "app_secret"},  # feishu/channel.py: if not app_id or not app_secret: return
    "qq": {"app_id", "secret"},  # qq/channel.py: if not app_id or not secret
    "wecom": {"bot_id", "secret"},  # wecom/channel.py: if not bot_id or not secret
}


@pytest.mark.parametrize("channel, expected", sorted(EXPECTED_REQUIRED.items()))
def test_required_markers_match_audit(channel: str, expected: set[str]) -> None:
    specs = channel_field_specs(channel)
    marked = {path for path, spec in specs.items() if spec.get("required")}
    assert marked == expected
