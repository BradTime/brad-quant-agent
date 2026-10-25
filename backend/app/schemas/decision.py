from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class DecisionRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codes: list[str] = Field(min_length=1, max_length=20)
    asOf: date
