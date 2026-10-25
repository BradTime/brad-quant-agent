from pydantic import BaseModel, ConfigDict, Field


class FilingProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    userId: str = Field(min_length=1, max_length=36)
    filingReference: str = Field(min_length=1, max_length=256)
    evidenceDocumentSha256: str = Field(
        pattern=r"^[0-9a-fA-F]{64}$"
    )
    professionalEligibilityConfirmed: bool
    brokerSimulationPermissionConfirmed: bool


class BrokerBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    userId: str = Field(min_length=1, max_length=36)
    filingProfileId: str = Field(min_length=1, max_length=36)
    accountId: str = Field(min_length=1, max_length=128)
    strategyId: str = Field(min_length=1, max_length=128)


class RehearsalOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bindingId: str = Field(min_length=1, max_length=36)
    idempotencyKey: str = Field(min_length=8, max_length=64)
    code: str
    side: str
    qty: int = Field(gt=0)
    limitPrice: float = Field(gt=0, allow_inf_nan=False)
    stepUpToken: str = Field(min_length=20, max_length=4096)
