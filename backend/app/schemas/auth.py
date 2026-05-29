"""Auth request schemas (response envelopes are built in the service layer)."""

from __future__ import annotations

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refreshToken: str
