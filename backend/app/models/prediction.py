"""M3 model registry, forecasts, regimes, and allocation audit."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class PredictionModelRun(Base):
    __tablename__ = "prediction_model_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    feature_schema_version: Mapped[str] = mapped_column(String(32))
    data_sha256: Mapped[str] = mapped_column(String(64))
    artifact_path: Mapped[str | None] = mapped_column(String(1024))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    metrics_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    training_start: Mapped[date] = mapped_column(Date)
    training_end: Mapped[date] = mapped_column(Date)
    is_champion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PredictionForecast(Base):
    __tablename__ = "prediction_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id",
            "code",
            "signal_date",
            name="uq_prediction_forecast_model_code_date",
        ),
        Index(
            "ix_prediction_forecasts_code_date",
            "code",
            "signal_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("prediction_model_runs.id", ondelete="RESTRICT")
    )
    code: Mapped[str] = mapped_column(String(16))
    signal_date: Mapped[date] = mapped_column(Date)
    probability_up: Mapped[float] = mapped_column(Float)
    return_p10: Mapped[float] = mapped_column(Float)
    return_p50: Mapped[float] = mapped_column(Float)
    return_p90: Mapped[float] = mapped_column(Float)
    feature_sha256: Mapped[str] = mapped_column(String(64))
    inferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

