"""The alarm manager: lifecycle plus side effects."""

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.script import Script
import homeassistant.util.dt as dt_util

from .const import (
    DEFAULT_ARCHIVE_DELAY,
    DOMAIN,
    EVENT_ACTION_ACKNOWLEDGED,
    EVENT_ACTION_ARCHIVED,
    EVENT_ACTION_CLEARED,
    EVENT_ACTION_RAISED,
    EVENT_ACTION_REACTIVATED,
    EVENT_ALARM,
    SIGNAL_UPDATE,
)
from .lifecycle import AlarmBook
from .models import Alarm, Rule

_LOGGER = logging.getLogger(__name__)


class AlarmManager:
    """Owns the open alarm list and everything that happens around it."""

    def __init__(self, hass: HomeAssistant, store, config: dict[str, Any]) -> None:
        """Set up the manager."""
        self.hass = hass
        self.store = store
        self.config = config
        self.book = AlarmBook()
        self.notifier = None  # set by __init__.py once created
        # Set by the rule engine so acknowledge/activate actions can be found.
        self.get_rule: Callable[[str | None], Rule | None] = lambda rule_id: None
        self._archive_timers: dict[str, CALLBACK_TYPE] = {}

    # -- setup / teardown ------------------------------------------------

    async def async_load(self) -> None:
        """Restore open alarms from the previous run."""
        data = await self.store.async_load_state()
        self.book.load(data.get("alarms", []))
        # Alarms that were already acknowledged and inactive when Home
        # Assistant stopped still need their archive timer.
        for alarm in list(self.book.open_alarms):
            if alarm.archivable:
                self._schedule_archive(alarm)
        _LOGGER.debug("Restored %s open alarms", len(self.book.open_alarms))

    async def async_shutdown(self) -> None:
        """Cancel timers and flush state."""
        for cancel in self._archive_timers.values():
            cancel()
        self._archive_timers.clear()
        await self.store.async_flush_state({"alarms": self.book.as_list()})

    # -- transitions -----------------------------------------------------

    @callback
    def raise_alarm(
        self,
        key: str,
        *,
        name: str,
        level: str,
        entity_id: str | None = None,
        rule_id: str | None = None,
        message: str | None = None,
        notify: bool = True,
        notify_targets: list[str] | None = None,
    ) -> Alarm:
        """Raise or reactivate an alarm.

        ``notify_targets``, when given, restricts notification to just those
        person entity ids for this alarm - used when a notification was
        addressed to one specific person rather than raised through a rule.
        """
        alarm, created, became_active = self.book.raise_alarm(
            key,
            name=name,
            level=level,
            now=dt_util.utcnow(),
            entity_id=entity_id,
            rule_id=rule_id,
            message=message,
        )
        # Coming back active cancels a pending archive.
        self._cancel_archive(key)

        if created:
            _LOGGER.debug("New alarm %s (%s)", alarm.name, alarm.key)
            self._fire(EVENT_ACTION_RAISED, alarm)
        else:
            self._fire(EVENT_ACTION_REACTIVATED, alarm)

        # Both the on_activate actions and the phone notification mirror
        # whether the condition is active right now, not whether this is a
        # "new" alarm - so a fault that comes back after having gone quiet
        # fires again, even though it is still the same alarm for
        # acknowledgement purposes.
        if became_active:
            self._run_rule_actions(alarm, "on_activate")
            if notify and self.notifier is not None:
                self.hass.async_create_task(
                    self.notifier.async_notify_new(alarm, targets_override=notify_targets)
                )

        self._changed()
        return alarm

    @callback
    def clear_alarm(self, key: str, *, run_actions: bool = True) -> Alarm | None:
        """Mark an alarm inactive. It stays in the list until acknowledged.

        ``run_actions=False`` skips the rule's ``on_clear`` sequence. Used
        when the clear is administrative - a rule being disabled or deleted
        should not run the user's "the fault went away" actions, because the
        fault did not go away.
        """
        alarm = self.book.clear_alarm(key, dt_util.utcnow())
        if alarm is None:
            return None
        self._fire(EVENT_ACTION_CLEARED, alarm)
        if run_actions:
            self._run_rule_actions(alarm, "on_clear")
        # The fault is gone, so the phone notification about it should be
        # too - it stays in the alarm list (dimmed) until acknowledged, but
        # a notification for a condition that is no longer true is just
        # noise on the phone.
        if self.notifier is not None:
            self.hass.async_create_task(self.notifier.async_clear_notification(alarm))
        if alarm.archivable:
            self._schedule_archive(alarm)
        self._changed()
        return alarm

    async def async_acknowledge(
        self,
        alarm_id: str,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
        context: Context | None = None,
    ) -> Alarm | None:
        """Acknowledge an alarm, recording who and when."""
        alarm = self.book.acknowledge(
            alarm_id,
            user_id=user_id,
            user_name=user_name,
            now=dt_util.utcnow(),
        )
        if alarm is None:
            return None

        _LOGGER.debug("Alarm %s acknowledged by %s", alarm.name, user_name or user_id)
        self._fire(EVENT_ACTION_ACKNOWLEDGED, alarm)
        await self._async_run_rule_actions(alarm, "on_acknowledge", context=context)

        if self.notifier is not None:
            self.hass.async_create_task(self.notifier.async_clear_notification(alarm))
        if alarm.archivable:
            self._schedule_archive(alarm)
        self._changed()
        return alarm

    async def async_acknowledge_all(
        self,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
        context: Context | None = None,
    ) -> int:
        """Acknowledge every open unacknowledged alarm."""
        count = 0
        for alarm in list(self.book.open_alarms):
            if alarm.acknowledged:
                continue
            if await self.async_acknowledge(
                alarm.id, user_id=user_id, user_name=user_name, context=context
            ):
                count += 1
        return count

    # -- archiving -------------------------------------------------------

    def _archive_delay_for(self, alarm: Alarm) -> int:
        rule = self.get_rule(alarm.rule_id)
        if rule is not None and rule.archive_delay is not None:
            return max(0, rule.archive_delay)
        return max(0, int(self.config.get("archive_delay", DEFAULT_ARCHIVE_DELAY)))

    @callback
    def _schedule_archive(self, alarm: Alarm) -> None:
        """Archive after the grace period, so flapping sensors stay one alarm."""
        self._cancel_archive(alarm.key)
        delay = self._archive_delay_for(alarm)
        if delay <= 0:
            self.hass.async_create_task(self._async_archive(alarm.key))
            return

        key = alarm.key

        @callback
        def _fire_archive(_now) -> None:
            self._archive_timers.pop(key, None)
            self.hass.async_create_task(self._async_archive(key))

        self._archive_timers[key] = async_call_later(self.hass, delay, _fire_archive)

    @callback
    def _cancel_archive(self, key: str) -> None:
        cancel = self._archive_timers.pop(key, None)
        if cancel is not None:
            cancel()

    async def _async_archive(self, key: str) -> None:
        """Move an acknowledged, inactive alarm to history."""
        alarm = self.book.archive(key, dt_util.utcnow())
        if alarm is None:
            return
        self._fire(EVENT_ACTION_ARCHIVED, alarm)
        try:
            await self.store.async_append_history(alarm.as_dict())
        except OSError as err:  # pragma: no cover - defensive
            _LOGGER.error("Could not write alarm history: %s", err)
        self._changed()

    # -- actions ---------------------------------------------------------

    @callback
    def _run_rule_actions(self, alarm: Alarm, field: str) -> None:
        self.hass.async_create_task(self._async_run_rule_actions(alarm, field))

    async def _async_run_rule_actions(
        self, alarm: Alarm, field: str, *, context: Context | None = None
    ) -> None:
        """Run the service calls configured on the rule for this transition."""
        rule = self.get_rule(alarm.rule_id)
        if rule is None:
            return
        sequence = getattr(rule, field, None)
        if not sequence:
            return
        try:
            script = Script(
                self.hass,
                sequence,
                f"{rule.name} {field}",
                DOMAIN,
            )
            await script.async_run(
                run_variables={"alarm": alarm.as_dict(), "rule": rule.as_dict()},
                context=context or Context(),
            )
        except Exception:  # noqa: BLE001 - never let a user action break the alarm
            _LOGGER.exception("Error running %s actions for rule %s", field, rule.id)

    # -- plumbing --------------------------------------------------------

    @callback
    def _fire(self, action: str, alarm: Alarm) -> None:
        self.hass.bus.async_fire(
            EVENT_ALARM, {"action": action, "alarm": alarm.as_dict()}
        )

    @callback
    def _changed(self) -> None:
        """Persist (debounced) and push the new state to panel and entities."""
        self.store.async_save_state(lambda: {"alarms": self.book.as_list()})
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)

    # -- reading ---------------------------------------------------------

    @callback
    def snapshot(self) -> dict[str, Any]:
        """Everything the panel needs for the alarm list."""
        return {
            "alarms": [alarm.as_dict() for alarm in self.book.open_alarms],
            "counts": self.counts(),
        }

    @callback
    def counts(self) -> dict[str, int]:
        """Counters used by sensors and by the panel header."""
        return {
            "open": self.book.count(),
            "active": self.book.count(active=True),
            "unacknowledged": self.book.count(acknowledged=False),
            "active_unacknowledged": self.book.count(active=True, acknowledged=False),
        }

    @callback
    def highest_level(self) -> str | None:
        """Most severe level among active alarms."""
        active = [a for a in self.book.open_alarms if a.active]
        if not active:
            return None
        return max(active, key=lambda a: a.severity).level
