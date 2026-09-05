"""Irreversible redaction for consented training artifacts."""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_INTERNATIONAL_PHONE = re.compile(r"(?<!\w)\+\d(?:[\d ()-]{7,18}\d)")
_CN_ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IPV4 = re.compile(
    r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*"
    r"[\"']?[^\s,\"'}]{6,}"
)
_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_CN_NAME = re.compile(r"(?:姓名|联系人|收件人)\s*[:：]\s*[\u4e00-\u9fff·]{2,20}")
_CN_ADDRESS = re.compile(
    r"[\u4e00-\u9fff]{2,}(?:省|自治区|市)[\u4e00-\u9fff0-9]{2,}"
    r"(?:市|区|县|旗|街道|路|号)[\u4e00-\u9fff0-9室栋单元路街号-]{0,40}"
)
_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "email",
    "ip",
    "password",
    "phone",
    "secret",
    "token",
    "user_id",
    "userid",
}
_SCANNERS = (
    _EMAIL,
    _PHONE,
    _INTERNATIONAL_PHONE,
    _CN_ID,
    _PAYMENT_CARD,
    _IPV4,
    _BEARER,
    _JWT,
    _SECRET_ASSIGNMENT,
    _CN_NAME,
    _CN_ADDRESS,
)


class RedactionError(ValueError):
    """The artifact still contains a recognized sensitive value."""


def redact_text(value: str, *, user_id: str | None = None) -> str:
    text = value
    if user_id:
        text = text.replace(user_id, "[USER]")
    replacements = (
        (_EMAIL, "[EMAIL]"),
        (_PHONE, "[PHONE]"),
        (_INTERNATIONAL_PHONE, "[PHONE]"),
        (_CN_ID, "[NATIONAL_ID]"),
        (_PAYMENT_CARD, "[PAYMENT_CARD]"),
        (_IPV4, "[IP]"),
        (_BEARER, "[TOKEN]"),
        (_JWT, "[TOKEN]"),
        (_SECRET_ASSIGNMENT, "[SECRET]"),
        (_UUID, "[ID]"),
        (_CN_NAME, "[NAME]"),
        (_CN_ADDRESS, "[ADDRESS]"),
    )
    for pattern, replacement in replacements:
        text = pattern.sub(replacement, text)
    for term in (
        item.strip()
        for item in settings.training_redaction_blocked_terms.split(",")
        if item.strip()
    ):
        text = text.replace(term, "[IDENTITY]")
    return text


def redact_payload(value: Any, *, user_id: str | None = None) -> Any:
    if isinstance(value, str):
        return redact_text(value, user_id=user_id)
    if isinstance(value, list):
        return [redact_payload(item, user_id=user_id) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item, user_id=user_id) for item in value]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or any(
                token in normalized for token in ("password", "secret", "token")
            ):
                output[str(key)] = "[REDACTED]"
            else:
                output[str(key)] = redact_payload(item, user_id=user_id)
        return output
    return value


def sensitive_matches(value: Any) -> list[str]:
    text = str(value)
    labels: list[str] = []
    for label, pattern in zip(
        (
            "email",
            "phone",
            "international_phone",
            "national_id",
            "payment_card",
            "ip",
            "bearer",
            "jwt",
            "secret",
            "name",
            "address",
        ),
        _SCANNERS,
        strict=True,
    ):
        if pattern.search(text):
            labels.append(label)
    for term in (
        item.strip()
        for item in settings.training_redaction_blocked_terms.split(",")
        if item.strip()
    ):
        if term in text:
            labels.append("blocked_term")
            break
    return labels


def assert_redacted(value: Any) -> None:
    matches = sensitive_matches(value)
    if matches:
        raise RedactionError("训练数据仍包含敏感信息: " + ",".join(matches))
