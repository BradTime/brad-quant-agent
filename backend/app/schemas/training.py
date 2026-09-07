"""Training consent, feedback, review, and dataset request contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ISSUE_LABELS = {
    "incorrect",
    "unsupported",
    "missing_data",
    "wrong_tool",
    "unsafe_advice",
    "unclear",
    "other",
}


class ConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class FeedbackUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["up", "down"]
    issueLabels: list[str] = Field(default_factory=list, max_length=7)
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("issueLabels")
    @classmethod
    def validate_labels(cls, value: list[str]) -> list[str]:
        labels = sorted(set(value))
        if any(label not in ISSUE_LABELS for label in labels):
            raise ValueError("包含不支持的问题标签")
        return labels


class CandidateReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["approved", "rejected", "deprecated"]
    taskType: Literal[
        "tool-routing", "grounded-response", "honesty-compliance"
    ] = "grounded-response"
    idealAnswer: str | None = Field(default=None, max_length=16000)
    qualityLabels: list[str] = Field(default_factory=list, max_length=20)
    reviewNote: str | None = Field(default=None, max_length=1000)


class DatasetBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
