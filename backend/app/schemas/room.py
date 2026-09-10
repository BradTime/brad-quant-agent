from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TotpEnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=8, max_length=128)


class TotpConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")


class StepUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=8, max_length=128)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    recoveryCode: str | None = Field(
        default=None,
        min_length=16,
        max_length=32,
        pattern=r"^[A-Fa-f0-9-]+$",
    )
    purpose: Literal[
        "change_decision_mode",
        "delete_account",
        "override_decision",
        "release_kill_switch",
        "reset_totp",
    ]

    @model_validator(mode="after")
    def exactly_one_factor(self) -> "StepUpRequest":
        if bool(self.code) == bool(self.recoveryCode):
            raise ValueError("必须且只能提交动态验证码或恢复码")
        return self


class ChangeModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["research_only", "manual_review", "simulation_ready"]
    reason: str = Field(min_length=10, max_length=500)
    stepUpToken: str = Field(min_length=20, max_length=4096)


class TotpResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stepUpToken: str = Field(min_length=20, max_length=4096)


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=500)


class ReleaseKillSwitchRequest(KillSwitchRequest):
    stepUpToken: str = Field(min_length=20, max_length=4096)


class DecisionOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "reject", "modify"]
    reason: str = Field(min_length=10, max_length=500)
    weights: dict[str, float] | None = None
    stepUpToken: str = Field(min_length=20, max_length=4096)
