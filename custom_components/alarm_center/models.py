"""Data models for Alarm Center.

This module deliberately has no Home Assistant imports so the alarm
lifecycle can be unit tested without a running Home Assistant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .const import (
    DEFAULT_AUTO_RULE_LEVEL,
    KIND_PROBLEM,
    LEVEL_SEVERITY,
    LEVEL_WARNING,
)


def utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass
class Alarm:
    """A single alarm instance.

    ``key`` is the stable identity of the underlying condition, ``id`` is the
    identity of this particular occurrence. An alarm that goes inactive and
    active again without being acknowledged keeps both.
    """

    key: str
    name: str
    level: str = LEVEL_WARNING
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    entity_id: str | None = None
    rule_id: str | None = None
    message: str | None = None
    active: bool = True
    acknowledged: bool = False
    activated_at: datetime = field(default_factory=utcnow)
    last_activated_at: datetime = field(default_factory=utcnow)
    deactivated_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    acknowledged_by_name: str | None = None
    activation_count: int = 1
    archived_at: datetime | None = None

    @property
    def severity(self) -> int:
        """Numeric severity, higher is worse. Useful for sorting."""
        return LEVEL_SEVERITY.get(self.level, 0)

    @property
    def archivable(self) -> bool:
        """An alarm leaves the list only when acknowledged *and* inactive."""
        return self.acknowledged and not self.active

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage and for the panel."""
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "level": self.level,
            "entity_id": self.entity_id,
            "rule_id": self.rule_id,
            "message": self.message,
            "active": self.active,
            "acknowledged": self.acknowledged,
            "activated_at": _iso(self.activated_at),
            "last_activated_at": _iso(self.last_activated_at),
            "deactivated_at": _iso(self.deactivated_at),
            "acknowledged_at": _iso(self.acknowledged_at),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_by_name": self.acknowledged_by_name,
            "activation_count": self.activation_count,
            "archived_at": _iso(self.archived_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Alarm:
        """Restore from storage."""
        return cls(
            id=data["id"],
            key=data["key"],
            name=data["name"],
            level=data.get("level", LEVEL_WARNING),
            entity_id=data.get("entity_id"),
            rule_id=data.get("rule_id"),
            message=data.get("message"),
            active=data.get("active", False),
            acknowledged=data.get("acknowledged", False),
            activated_at=_dt(data.get("activated_at")) or utcnow(),
            last_activated_at=_dt(data.get("last_activated_at")) or utcnow(),
            deactivated_at=_dt(data.get("deactivated_at")),
            acknowledged_at=_dt(data.get("acknowledged_at")),
            acknowledged_by=data.get("acknowledged_by"),
            acknowledged_by_name=data.get("acknowledged_by_name"),
            activation_count=data.get("activation_count", 1),
            archived_at=_dt(data.get("archived_at")),
        )


@dataclass
class Rule:
    """A user (or auto) defined alarm rule."""

    id: str
    name: str
    kind: str = KIND_PROBLEM
    level: str = DEFAULT_AUTO_RULE_LEVEL
    enabled: bool = True
    entity_id: str | None = None
    # numeric
    above: float | None = None
    below: float | None = None
    hysteresis: float = 0.0
    # state
    state: str | None = None
    # template
    template: str | None = None
    # timing
    for_seconds: int = 0
    archive_delay: int | None = None  # None -> use global setting
    # behaviour
    unavailable_is_problem: bool = False
    notify: bool = True
    notify_targets: list[str] | None = None  # None -> every enabled target
    message: str | None = None
    # actions
    on_activate: list[dict[str, Any]] = field(default_factory=list)
    on_acknowledge: list[dict[str, Any]] = field(default_factory=list)
    on_clear: list[dict[str, Any]] = field(default_factory=list)
    # bookkeeping
    auto: bool = False
    source_entity_id: str | None = None  # for auto rules, the discovered entity

    @property
    def alarm_key(self) -> str:
        """Stable alarm key produced by this rule."""
        return f"rule:{self.id}"

    def as_dict(self) -> dict[str, Any]:
        """Serialise for storage and for the panel."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "level": self.level,
            "enabled": self.enabled,
            "entity_id": self.entity_id,
            "above": self.above,
            "below": self.below,
            "hysteresis": self.hysteresis,
            "state": self.state,
            "template": self.template,
            "for_seconds": self.for_seconds,
            "archive_delay": self.archive_delay,
            "unavailable_is_problem": self.unavailable_is_problem,
            "notify": self.notify,
            "notify_targets": self.notify_targets,
            "message": self.message,
            "on_activate": self.on_activate,
            "on_acknowledge": self.on_acknowledge,
            "on_clear": self.on_clear,
            "auto": self.auto,
            "source_entity_id": self.source_entity_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        """Restore from storage or from the panel."""
        return cls(
            id=data["id"],
            name=data.get("name") or data["id"],
            kind=data.get("kind", KIND_PROBLEM),
            level=data.get("level", DEFAULT_AUTO_RULE_LEVEL),
            enabled=data.get("enabled", True),
            entity_id=data.get("entity_id"),
            above=_float_or_none(data.get("above")),
            below=_float_or_none(data.get("below")),
            hysteresis=float(data.get("hysteresis") or 0.0),
            state=data.get("state"),
            template=data.get("template"),
            for_seconds=int(data.get("for_seconds") or 0),
            archive_delay=(
                None
                if data.get("archive_delay") in (None, "")
                else int(data["archive_delay"])
            ),
            unavailable_is_problem=data.get("unavailable_is_problem", False),
            notify=data.get("notify", True),
            notify_targets=data.get("notify_targets"),
            message=data.get("message"),
            on_activate=list(data.get("on_activate") or []),
            on_acknowledge=list(data.get("on_acknowledge") or []),
            on_clear=list(data.get("on_clear") or []),
            auto=data.get("auto", False),
            source_entity_id=data.get("source_entity_id"),
        )


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
