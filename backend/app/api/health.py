"""Health check endpoint."""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.response import error, success
from app.db.session import engine

router = APIRouter()


@router.get("/health")
def health() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        return error(f"database unavailable: {exc}", code=503, http_status=503)
    return success({"status": "ok", "database": "ok"}, message="ok")
