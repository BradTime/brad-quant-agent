"""Create tables from the ORM metadata.

Phase 0 uses ``create_all`` for speed; switch to Alembic migrations once the
schema stabilizes.
"""

from __future__ import annotations

from app.db.base import Base
from app.db.session import engine


def init_db() -> None:
    import app.models  # noqa: F401  (register mappers on Base.metadata)

    Base.metadata.create_all(bind=engine)
