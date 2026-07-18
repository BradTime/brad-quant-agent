"""Minimal SMTP sender for account verification messages."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from urllib.parse import quote

from app.core.config import settings


def send_verification_email(email: str, token: str) -> None:
    if not settings.frontend_url.startswith("https://"):
        raise RuntimeError("verification email requires an HTTPS FRONTEND_URL")
    verification_url = f"{settings.frontend_url.rstrip('/')}/verify?token={quote(token)}"
    message = EmailMessage()
    message["Subject"] = "验证您的 Quant Agent 邮箱"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(
        "请打开以下链接完成邮箱验证（链接将在"
        f" {settings.auth_verification_expire_hours} 小时后失效）：\n{verification_url}"
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)
