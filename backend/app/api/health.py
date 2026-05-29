"""Health check endpoint."""

from fastapi import APIRouter

from app.core.response import success

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return success({"status": "ok"}, message="ok")
