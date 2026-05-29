"""Auth service: registration, authentication, and token assembly.

User data is scoped by a stable ``id`` (uuid4) so everything downstream can be
``user_id``-isolated (multi-user ready). Response shape matches the frontend
``AuthResponse`` = ``{ user, token, refreshToken }`` with camelCase user fields.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.db.session import SessionLocal
from app.models.user import User


def serialize_user(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar": user.avatar,
        "role": user.role,
        "createdAt": user.created_at.isoformat() if user.created_at else None,
        "updatedAt": user.updated_at.isoformat() if user.updated_at else None,
    }


def build_auth_response(user: User) -> dict:
    return {
        "user": serialize_user(user),
        "token": create_access_token(user.id),
        "refreshToken": create_refresh_token(user.id),
    }


def register_user(email: str, password: str, name: str | None) -> dict:
    email = email.strip().lower()
    if not email or not password:
        raise ValueError("邮箱和密码不能为空")
    with SessionLocal() as session:
        exists = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if exists is not None:
            raise ValueError("该邮箱已注册")
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            name=(name or email.split("@")[0]),
            password_hash=hash_password(password),
            role="user",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return build_auth_response(user)


def authenticate(email: str, password: str) -> dict:
    email = email.strip().lower()
    with SessionLocal() as session:
        user = session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if user is None or not verify_password(password, user.password_hash):
            raise ValueError("邮箱或密码错误")
        return build_auth_response(user)


def get_user_by_id(user_id: str) -> User | None:
    with SessionLocal() as session:
        return session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()
