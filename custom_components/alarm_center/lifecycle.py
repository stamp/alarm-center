"""The alarm lifecycle state machine.

Kept free of Home Assistant imports on purpose: everything here is pure
bookkeeping, so it can be tested with plain unittest. All side effects
(timers, notifications, persistence, dispatching) live in ``manager.py``.

Lifecycle rules implemented here:

* An alarm stays in the open list until it is BOTH acknowledged and inactive.
* If an alarm toggles active/inactive without being acknowledged, it is the
  same alarm - only ``activation_count`` and ``last_activated_at`` change.
* Acknowledgement records who and when.
* Activation and deactivation timestamps are kept.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .models import Alarm, utcnow


class AlarmBook:
    """Holds the currently open alarms, keyed by their stable alarm key."""

    def __init__(self) -> None:
        self._by_key: dict[str, Alarm] = {}

    # -- reading ---------------------------------------------------------

    @property
    def open_alarms(self) -> list[Alarm]:
        """All open alarms, most severe and most recent first."""
        return sorted(
            self._by_key.values(),
            key=lambda a: (a.acknowledged, -a.severity, -a.last_activated_at.timestamp()),
        )

    def get(self, key: str) -> Alarm | None:
        """Return the open alarm for a key, if any."""
        return self._by_key.get(key)

    def get_by_id(self, alarm_id: str) -> Alarm | None:
        """Return the open alarm with this instance id, if any."""
        return next((a for a in self._by_key.values() if a.id == alarm_id), None)

    def is_active(self, key: str) -> bool:
        """Whether there is an open and currently active alarm for this key."""
        alarm = self._by_key.get(key)
        return bool(alarm and alarm.active)

    def count(self, *, active: bool | None = None, acknowledged: bool | None = None) -> int:
        """Count open alarms matching the given flags."""
        return sum(
            1
            for a in self._by_key.values()
            if (active is None or a.active == active)
            and (acknowledged is None or a.acknowledged == acknowledged)
        )

    # -- transitions -----------------------------------------------------

    def raise_alarm(
        self,
        key: str,
        *,
        name: str,
        level: str,
        now: datetime | None = None,
        **fields: Any,
    ) -> tuple[Alarm, bool, bool]:
        """Raise an alarm for ``key``.

        Returns ``(alarm, created, became_active)``. ``created`` is False
        when an open alarm for the same key was reactivated instead of a new
        one created. ``became_active`` is True whenever this call is what
        made the alarm active - covers both a brand new alarm and one that
        had gone inactive coming back, which matters for anything (like
        notifications) that should track the condition's current state
        rather than the alarm's identity.
        """
        now = now or utcnow()
        alarm = self._by_key.get(key)

        if alarm is None:
            alarm = Alarm(
                key=key,
                name=name,
                level=level,
                activated_at=now,
                last_activated_at=now,
                **fields,
            )
            self._by_key[key] = alarm
            return alarm, True, True

        # Same condition came back. Keep identity, ack state and first
        # activation timestamp - this is not a new alarm.
        was_active = alarm.active
        alarm.active = True
        alarm.deactivated_at = None
        alarm.name = name
        alarm.level = level
        for attr, value in fields.items():
            if value is not None:
                setattr(alarm, attr, value)
        if not was_active:
            alarm.last_activated_at = now
            alarm.activation_count += 1
        return alarm, False, not was_active

    def clear_alarm(self, key: str, now: datetime | None = None) -> Alarm | None:
        """Mark the alarm for ``key`` inactive. Returns it if it changed."""
        alarm = self._by_key.get(key)
        if alarm is None or not alarm.active:
            return None
        alarm.active = False
        alarm.deactivated_at = now or utcnow()
        return alarm

    def acknowledge(
        self,
        alarm_id: str,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
        now: datetime | None = None,
    ) -> Alarm | None:
        """Acknowledge an open alarm. Returns it if it changed."""
        alarm = self.get_by_id(alarm_id)
        if alarm is None or alarm.acknowledged:
            return None
        alarm.acknowledged = True
        alarm.acknowledged_at = now or utcnow()
        alarm.acknowledged_by = user_id
        alarm.acknowledged_by_name = user_name
        return alarm

    def archive(self, key: str, now: datetime | None = None) -> Alarm | None:
        """Remove an alarm from the open list. Returns the archived alarm."""
        alarm = self._by_key.get(key)
        if alarm is None or not alarm.archivable:
            return None
        alarm.archived_at = now or utcnow()
        return self._by_key.pop(key)

    # -- persistence -----------------------------------------------------

    def as_list(self) -> list[dict[str, Any]]:
        """Serialise every open alarm."""
        return [alarm.as_dict() for alarm in self._by_key.values()]

    def load(self, data: Iterable[dict[str, Any]]) -> None:
        """Restore open alarms from storage."""
        self._by_key = {}
        for item in data:
            try:
                alarm = Alarm.from_dict(item)
            except (KeyError, ValueError):
                continue
            self._by_key[alarm.key] = alarm
