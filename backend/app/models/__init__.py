"""ORM models and schemas (include point-in-time fields for backtest correctness)."""

from app.models.admin import AdminPrivilegeAudit
from app.models.auth import AuthThrottle, EmailVerification, VerificationEmailOutbox
from app.models.backtest import BacktestRun
from app.models.brief import MorningBrief
from app.models.chat import ChatMessage, ChatSession, UserMemory
from app.models.decision import DecisionEvent, DecisionRun
from app.models.document import Document
from app.models.extra import (
    CapitalFlow,
    CapitalFlowVintage,
    DragonTiger,
    FinancialSummary,
    NewsItem,
)
from app.models.ingestion import IngestionRun
from app.models.job import BacktestJob
from app.models.market import (
    AdjustFactor,
    DailyBar,
    Instrument,
    InstrumentIndustryVintage,
    InstrumentStatusHistory,
    MinuteBar,
)
from app.models.prediction import (
    PortfolioAllocationDecision,
    PortfolioRiskProfile,
    PredictionForecast,
    PredictionModelRun,
    PredictionPromotionAudit,
    RegimeSnapshot,
)
from app.models.research import ResearchReport
from app.models.strategy import Strategy, StrategyVersion
from app.models.trading import SimAccount, SimOrder, SimPosition, SimTrade
from app.models.training import (
    AIGenerationTrace,
    AITrainingFeedback,
    TrainingCandidate,
    TrainingConsent,
    TrainingDataset,
    TrainingDatasetItem,
)
from app.models.universe import UniverseMembershipDaily, UniverseSnapshotDaily
from app.models.user import User
from app.models.watchlist import WatchlistItem

__all__ = [
    "User",
    "AdminPrivilegeAudit",
    "AuthThrottle",
    "EmailVerification",
    "VerificationEmailOutbox",
    "Instrument",
    "InstrumentIndustryVintage",
    "InstrumentStatusHistory",
    "DailyBar",
    "MinuteBar",
    "AdjustFactor",
    "CapitalFlow",
    "CapitalFlowVintage",
    "FinancialSummary",
    "DragonTiger",
    "NewsItem",
    "IngestionRun",
    "WatchlistItem",
    "MorningBrief",
    "ChatSession",
    "ChatMessage",
    "UserMemory",
    "DecisionEvent",
    "DecisionRun",
    "Document",
    "ResearchReport",
    "PredictionModelRun",
    "PredictionForecast",
    "PredictionPromotionAudit",
    "PortfolioRiskProfile",
    "RegimeSnapshot",
    "PortfolioAllocationDecision",
    "BacktestRun",
    "BacktestJob",
    "Strategy",
    "StrategyVersion",
    "SimAccount",
    "SimOrder",
    "SimPosition",
    "SimTrade",
    "TrainingConsent",
    "AIGenerationTrace",
    "AITrainingFeedback",
    "TrainingCandidate",
    "TrainingDataset",
    "TrainingDatasetItem",
    "UniverseMembershipDaily",
    "UniverseSnapshotDaily",
]
