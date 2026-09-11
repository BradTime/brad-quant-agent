from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PredictionOpsEnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    jobType: Literal["weekly_train", "daily_infer"]
    scheduledFor: date
    codes: list[str] = Field(min_length=1, max_length=20)
    provider: Literal["lightgbm", "xgboost"] = "lightgbm"
