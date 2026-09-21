"""Explicit, default-off policy for the experimental preference fast path."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class PersonalizationGateConfig(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True)

    mode: Literal["off", "shadow", "enforce"] = "off"
    model: Literal["jev-1.13.0"] = "jev-1.13.0"
    api_key_env: str = Field(default="TYPESAFE_API_KEY", pattern=r"^[A-Z_][A-Z0-9_]*$")
    data_consent: bool = False
    timeout_seconds: float = Field(default=1.0, gt=0, le=10, allow_inf_nan=False)
    max_state_bytes: int = Field(default=12_000, ge=256, le=24_000)
    max_concurrent: int = Field(default=2, ge=1, le=8)
    requests_per_minute: int = Field(default=60, ge=1, le=600)
    failure_threshold: int = Field(default=3, ge=1, le=10)
    cooldown_seconds: float = Field(default=30.0, gt=0, le=300, allow_inf_nan=False)
    min_confidence: float = Field(default=0.98, ge=0.5, le=1, allow_inf_nan=False)
    min_choice_probability: float = Field(default=0.98, ge=0.5, le=1, allow_inf_nan=False)
    policy_digest: str = Field(default="", pattern=r"^([0-9a-f]{64})?$")

    @model_validator(mode="after")
    def require_explicit_consent(self):
        if self.mode != "off" and not self.data_consent:
            raise ValueError("Jev requires consent to send request, recent history and local preferences to TypeSafe")
        if self.mode == "enforce" and not self.policy_digest:
            raise ValueError("enforce requires the digest of a reviewed calibration or controlled experiment plan")
        return self
