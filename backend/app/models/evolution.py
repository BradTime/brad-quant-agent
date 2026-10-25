from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import PortableJSON


class EvolutionProgram(Base):
    __tablename__ = "evolution_programs"
    __table_args__ = (
        UniqueConstraint(
            "model_run_id", name="uq_evolution_program_model_run"
        ),
        Index(
            "ix_evolution_programs_stage_updated",
            "stage",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    model_run_id: Mapped[str] = mapped_column(
        ForeignKey("prediction_model_runs.id", ondelete="RESTRICT")
    )
    model_artifact_sha256: Mapped[str] = mapped_column(String(64))
    model_data_sha256: Mapped[str] = mapped_column(String(64))
    attestation_key_id: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_user_id_snapshot: Mapped[str] = mapped_column(String(36))
    stage: Mapped[str] = mapped_column(String(32))
    codes_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    started_on: Mapped[date] = mapped_column(Date)
    stage_started_on: Mapped[date] = mapped_column(Date)
    simulation_sessions: Mapped[int] = mapped_column(Integer)
    shadow_sessions: Mapped[int] = mapped_column(Integer)
    initial_equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    peak_equity: Mapped[float] = mapped_column(Float)
    holdings_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    champion_cash: Mapped[float] = mapped_column(Float)
    champion_equity: Mapped[float] = mapped_column(Float)
    champion_holdings_json: Mapped[
        dict[str, Any] | list[Any]
    ] = mapped_column(PortableJSON, nullable=False)
    metrics_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    claim_token: Mapped[str | None] = mapped_column(String(36))
    claim_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_signal_date: Mapped[date | None] = mapped_column(Date)
    failure_reason: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class EvolutionObservation(Base):
    __tablename__ = "evolution_observations"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "signal_date",
            name="uq_evolution_observation_program_signal",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(
        ForeignKey(
            "evolution_signal_commitments.id",
            ondelete="RESTRICT",
        ),
        unique=True,
    )
    program_id: Mapped[str] = mapped_column(
        ForeignKey("evolution_programs.id", ondelete="RESTRICT"),
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(32))
    signal_date: Mapped[date] = mapped_column(Date)
    label_date: Mapped[date] = mapped_column(Date)
    daily_return: Mapped[float] = mapped_column(Float)
    benchmark_return: Mapped[float] = mapped_column(Float)
    equity: Mapped[float] = mapped_column(Float)
    evidence_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    attestation_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvolutionSignalCommitment(Base):
    __tablename__ = "evolution_signal_commitments"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "signal_date",
            name="uq_evolution_commitment_program_signal",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        ForeignKey("evolution_programs.id", ondelete="RESTRICT"),
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(32))
    signal_date: Mapped[date] = mapped_column(Date)
    label_date: Mapped[date] = mapped_column(Date)
    model_artifact_sha256: Mapped[str] = mapped_column(String(64))
    universe_membership_sha256: Mapped[str] = mapped_column(String(64))
    evidence_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    attestation_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvolutionTransition(Base):
    __tablename__ = "evolution_transitions"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "sequence",
            name="uq_evolution_transition_program_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    program_id: Mapped[str] = mapped_column(
        ForeignKey("evolution_programs.id", ondelete="RESTRICT"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    from_stage: Mapped[str] = mapped_column(String(32))
    to_stage: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(128))
    metrics_sha256: Mapped[str] = mapped_column(String(64))
    evidence_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    previous_transition_sha256: Mapped[str | None] = mapped_column(
        String(64)
    )
    attestation_sha256: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BehaviorAttribution(Base):
    __tablename__ = "behavior_attributions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    override_id: Mapped[str] = mapped_column(
        ForeignKey("decision_overrides.id", ondelete="RESTRICT"),
        unique=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    user_id_snapshot: Mapped[str] = mapped_column(String(36))
    signal_date: Mapped[date] = mapped_column(Date)
    label_date: Mapped[date] = mapped_column(Date)
    strategy_return: Mapped[float] = mapped_column(Float)
    human_return: Mapped[float] = mapped_column(Float)
    return_delta: Mapped[float] = mapped_column(Float)
    behavior_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        PortableJSON, nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BehaviorAttributionAttempt(Base):
    __tablename__ = "behavior_attribution_attempts"

    override_id: Mapped[str] = mapped_column(
        ForeignKey("decision_overrides.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "BehaviorAttribution",
    "BehaviorAttributionAttempt",
    "EvolutionObservation",
    "EvolutionProgram",
    "EvolutionSignalCommitment",
    "EvolutionTransition",
]
