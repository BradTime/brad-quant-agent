from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class EvolutionEnrollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[str] = Field(min_length=1, max_length=20)


class EvolutionEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signalDate: date
