"""Versioned JSON envelopes for persisted payloads.

Legacy bare dict/list values are treated as ``schemaVersion=0`` and upgraded.
Corrupt or wrong-typed payloads raise ``JsonCorruptError`` instead of silently
falling back to empty defaults (H17).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

CURRENT_SCHEMA_VERSION = 1

T = TypeVar("T")


class JsonCorruptError(ValueError):
    """Persisted JSON cannot be decoded or fails schema checks."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class JsonEnvelope(BaseModel):
    """Common on-disk shape: ``{schemaVersion, payload}``."""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: int = Field(ge=0, default=CURRENT_SCHEMA_VERSION)
    payload: Any


def coerce_raw(raw: Any) -> Any:
    """Normalize SQLAlchemy JSON / legacy Text into a Python value."""
    if raw is None:
        return None
    if isinstance(raw, (dict, list, int, float, bool)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except (TypeError, ValueError) as exc:
            raise JsonCorruptError(f"invalid JSON text: {exc}") from exc
    raise JsonCorruptError(f"unsupported JSON storage type: {type(raw).__name__}")


def _upgrade_identity(version: int, payload: Any) -> Any:
    """Default upgrader: versions 0..CURRENT are accepted as-is."""
    if version > CURRENT_SCHEMA_VERSION:
        raise JsonCorruptError(f"unsupported schemaVersion={version}")
    return payload


def dump_envelope(payload: Any, *, version: int = CURRENT_SCHEMA_VERSION) -> dict:
    """Wrap a payload for persistence (JSON-safe via default=str)."""
    safe = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    return JsonEnvelope(schemaVersion=version, payload=safe).model_dump(mode="json")


def load_envelope(
    raw: Any,
    *,
    expect: Literal["dict", "list", "any"] = "any",
    field: str | None = None,
    upgrade: Callable[[int, Any], Any] | None = None,
) -> Any:
    """Decode storage value → unwrapped payload at CURRENT_SCHEMA_VERSION.

    Accepts:
    - envelope ``{schemaVersion, payload}``
    - legacy bare dict/list (treated as schemaVersion=0)
    """
    upgrade_fn = upgrade or _upgrade_identity
    try:
        value = coerce_raw(raw)
    except JsonCorruptError as exc:
        raise JsonCorruptError(str(exc), field=field) from exc

    if value is None:
        raise JsonCorruptError("missing JSON payload", field=field)

    version = 0
    payload: Any
    if isinstance(value, dict) and "schemaVersion" in value and "payload" in value:
        try:
            env = JsonEnvelope.model_validate(value)
        except Exception as exc:  # noqa: BLE001
            raise JsonCorruptError(f"invalid envelope: {exc}", field=field) from exc
        version = int(env.schemaVersion)
        payload = env.payload
    else:
        payload = value

    try:
        payload = upgrade_fn(version, payload)
    except JsonCorruptError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise JsonCorruptError(f"upgrade failed: {exc}", field=field) from exc

    if expect == "dict" and not isinstance(payload, dict):
        raise JsonCorruptError(
            f"expected object payload, got {type(payload).__name__}",
            field=field,
        )
    if expect == "list" and not isinstance(payload, list):
        raise JsonCorruptError(
            f"expected array payload, got {type(payload).__name__}",
            field=field,
        )
    return payload


def load_envelope_or_default(
    raw: Any,
    default: T,
    *,
    expect: Literal["dict", "list", "any"] = "any",
    field: str | None = None,
    allow_missing: bool = True,
) -> T:
    """Like ``load_envelope`` but returns ``default`` when raw is empty (not corrupt)."""
    if raw is None or raw == "" or raw == {}:
        if allow_missing:
            return default
        raise JsonCorruptError("missing JSON payload", field=field)
    # Empty list is a valid stored value for list fields — only treat None/"" as missing.
    if isinstance(raw, str) and not raw.strip():
        if allow_missing:
            return default
        raise JsonCorruptError("missing JSON payload", field=field)
    return load_envelope(raw, expect=expect, field=field)  # type: ignore[return-value]
