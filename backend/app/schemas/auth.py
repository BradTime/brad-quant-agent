"""Auth request schemas (response envelopes are built in the service layer)."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_CONTROL_OR_SPACE = re.compile(r"[\s\x00-\x1f\x7f]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_REGISTER_PASSWORD_CLASSES = (
    re.compile(r"[a-z]"),
    re.compile(r"[A-Z]"),
    re.compile(r"[0-9]"),
    re.compile(r"[^A-Za-z0-9]"),
)


class _AuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


def _validate_password_characters(password: str) -> str:
    if _CONTROL_OR_SPACE.search(password):
        raise ValueError("密码不能包含空白或控制字符")
    return password


def _validate_registration_password(password: str) -> str:
    _validate_password_characters(password)
    if not all(pattern.search(password) for pattern in _REGISTER_PASSWORD_CLASSES):
        raise ValueError("密码必须包含大小写字母、数字和特殊字符")
    return password


def _normalize_name(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = value.strip()
    if _CONTROL.search(value):
        raise ValueError("姓名不能包含控制字符")
    return value


class RegisterRequest(_AuthRequest):
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        return _validate_registration_password(password)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_name(value)


class LoginRequest(_AuthRequest):
    password: str = Field(min_length=1, max_length=256)

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        if _CONTROL.search(password):
            raise ValueError("密码不能包含控制字符")
        return password


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:
        return _validate_registration_password(password)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_name(value)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refreshToken: str
