"""Reminders, repeats and the end of quiet hours.

Three time-driven behaviours, all reading their settings live from the
config so a change in the panel takes effect on the next tick without a
restart:

* a daily digest listing what is still active,
* a per-level repeat for alarms that are still active *and* unacknowledged,
* flushing notifications that quiet hours held back, when the window ends.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
import homeassistant.util.dt as dt_util

from .const import LEVEL_SEVERITY, REMINDER_TICK_SECONDS
from .schedule import parse_hhmm

_LOGGER = logging.getLogger(__name__)


class ReminderScheduler:
    """Owns the clocks. All the sending itself lives in the notifier."""

    def __init__(self, hass: HomeAssistant, store, manager, notifier) -> None:
        """Set up the scheduler."""
        self.hass = hass
        self.store = store
        self.manager = manager
        self.notifier = notifier
        self._unsub: list[CALLBACK_TYPE] = []
        # Alarm id -> when it was last reminded about.
        self._last_reminder: dict[str, Any] = {}

    @property
    def _notify_config(self) -> dict[str, Any]:
        return self.store.config.get("notify", {})

    @property
    def _reminders(self) -> dict[str, Any]:
        return self._notify_config.get("reminders", {})

    # -- setup -----------------------------------------------------------

    async def async_setup(self) -> None:
        """Start the timers."""
        self._register()

    async def async_reload(self) -> None:
        """Re-register after a settings change, so new times take effect."""
        self._unregister()
        self._register()

    async def async_unload(self) -> None:
        """Stop everything."""
        self._unregister()
        self._last_reminder.clear()

    @callback
    def _register(self) -> None:
        # The repeat tick runs regardless of configuration and checks the
        # intervals itself - one timer is cheaper than re-registering
        # whenever a level's interval changes.
        self._unsub.append(
            async_track_time_interval(
                self.hass,
                self._handle_tick,
                timedelta(seconds=REMINDER_TICK_SECONDS),
            )
        )

        digest = self._reminders.get("digest", {})
        if digest.get("enabled", False):
            hour, minute = parse_hhmm(digest.get("time"), (7, 0))
            self._unsub.append(
                async_track_time_change(
                    self.hass, self._handle_digest, hour=hour, minute=minute, second=0
                )
            )

        quiet = self._notify_config.get("quiet_hours", {})
        if quiet.get("enabled", False) and quiet.get("send_after", True):
            hour, minute = parse_hhmm(quiet.get("end"), (7, 0))
            self._unsub.append(
                async_track_time_change(
                    self.hass, self._handle_quiet_end, hour=hour, minute=minute, second=0
                )
            )

    @callback
    def _unregister(self) -> None:
        for cancel in self._unsub:
            cancel()
        self._unsub.clear()

    # -- handlers --------------------------------------------------------

    async def _handle_digest(self, _now) -> None:
        """Send the "these are still active" summary."""
        digest = self._reminders.get("digest", {})
        min_level = digest.get("min_level", "warning")
        threshold = LEVEL_SEVERITY.get(min_level, 0)

        alarms = [
            alarm
            for alarm in self.manager.book.open_alarms
            if alarm.active and alarm.severity >= threshold
        ]
        if not alarms:
            _LOGGER.debug("Digest: nothing active, staying quiet")
            return
        await self.notifier.async_send_digest(alarms)

    async def _handle_quiet_end(self, _now) -> None:
        """Release whatever quiet hours held back."""
        await self.notifier.async_flush_deferred()

    async def _handle_tick(self, _now) -> None:
        """Re-notify alarms that are still active and unacknowledged."""
        repeat = self._reminders.get("repeat", {})
        if not any(repeat.values()):
            self._last_reminder.clear()
            return

        now = dt_util.utcnow()
        open_ids = set()

        for alarm in self.manager.book.open_alarms:
            open_ids.add(alarm.id)

            # Acknowledging is what stops the nagging - it means someone has
            # seen it and taken ownership, whether or not it is fixed yet.
            if not alarm.active or alarm.acknowledged:
                continue

            interval = int(repeat.get(alarm.level, 0) or 0)
            if interval <= 0:
                continue
            if self.notifier.is_silenced(alarm.level):
                continue

            last = self._last_reminder.get(alarm.id) or alarm.last_activated_at
            if (now - last).total_seconds() < interval:
                continue

            _LOGGER.debug("Reminder for %s (%s)", alarm.name, alarm.level)
            self._last_reminder[alarm.id] = now
            await self.notifier.async_send_reminder(alarm)

        # Forget alarms that have left the list, so a later alarm reusing
        # the id (it won't, but) never inherits a stale timestamp.
        for alarm_id in set(self._last_reminder) - open_ids:
            self._last_reminder.pop(alarm_id, None)
