"""Notifications for new alarms.

A target is a person plus the notify services that reach that person's
devices. Services are resolved automatically from the person's device
trackers (mobile_app), and can be overridden by hand in the panel.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.notify import (
    ATTR_DATA,
    ATTR_MESSAGE,
    ATTR_TITLE,
    DOMAIN as NOTIFY_DOMAIN,
)
from homeassistant.core import Event, HomeAssistant, callback
import homeassistant.util.dt as dt_util
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from .const import (
    LEVEL_CHANNEL,
    LEVEL_IMPORTANCE,
    LEVEL_SEVERITY,
    LEVEL_WARNING,
    NOTIFY_ACK_ACTION_PREFIX,
    NOTIFY_TAG_DIGEST,
    NOTIFY_TAG_PREFIX,
    TTS_STREAM_OFF,
)
from .schedule import in_window
from .models import Alarm

_LOGGER = logging.getLogger(__name__)

MOBILE_APP_DOMAIN = "mobile_app"
EVENT_MOBILE_APP_ACTION = "mobile_app_notification_action"

LEVEL_TITLES = {
    "critical": "Critical Alarm",
    "error": "Error",
    "warning": "Warning",
    "notice": "Notice",
}


class Notifier:
    """Sends notifications when new alarms appear."""

    def __init__(self, hass: HomeAssistant, store, manager) -> None:
        """Set up the notifier."""
        self.hass = hass
        self.store = store
        self.manager = manager
        self._unsub = None
        # Alarm ids held back by quiet hours, flushed when the window ends.
        self._deferred: dict[str, bool] = {}

    @property
    def config(self) -> dict[str, Any]:
        """Notification section of the config."""
        notify = self.store.config.setdefault(
            "notify",
            {"enabled": True, "targets": [], "tts": {"enabled": False, "streams": {}}},
        )
        notify.setdefault("tts", {"enabled": False, "streams": {}})
        notify.setdefault("reminders", {"digest": {}, "repeat": {}})
        notify.setdefault("quiet_hours", {"enabled": False})
        return notify

    @property
    def quiet_config(self) -> dict[str, Any]:
        """Quiet hours section."""
        return self.config.get("quiet_hours", {})

    @property
    def reminder_config(self) -> dict[str, Any]:
        """Reminder section."""
        return self.config.get("reminders", {})

    async def async_setup(self) -> None:
        """Listen for acknowledge actions coming back from the mobile app."""
        self._unsub = self.hass.bus.async_listen(
            EVENT_MOBILE_APP_ACTION, self._handle_mobile_action
        )

    async def async_unload(self) -> None:
        """Stop listening."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    # -- sending ---------------------------------------------------------

    # -- quiet hours -----------------------------------------------------

    @callback
    def is_silenced(self, level: str) -> bool:
        """Whether this level is currently held back by quiet hours."""
        quiet = self.quiet_config
        if not quiet.get("enabled", False):
            return False
        if level not in (quiet.get("levels") or []):
            return False
        return in_window(dt_util.now().time(), quiet.get("start"), quiet.get("end"))

    async def async_flush_deferred(self) -> None:
        """Send what quiet hours held back, once the window ends.

        Alarms that resolved themselves in the meantime are dropped rather
        than delivered - waking someone at 07:00 for a fault that cleared at
        01:00 is exactly the noise quiet hours exist to prevent.
        """
        deferred, self._deferred = self._deferred, {}
        if not deferred or not self.quiet_config.get("send_after", True):
            return

        for alarm_id in deferred:
            alarm = self.manager.book.get_by_id(alarm_id)
            if alarm is None or not alarm.active or alarm.acknowledged:
                continue
            await self.async_notify_new(alarm, ignore_quiet_hours=True)

    async def async_notify_new(
        self,
        alarm: Alarm,
        *,
        targets_override: list[str] | None = None,
        ignore_quiet_hours: bool = False,
        reminder: bool = False,
    ) -> None:
        """Notify everyone who should hear about this alarm becoming active.

        ``targets_override``, when given, restricts notification to exactly
        those person entity ids regardless of any rule's own restriction -
        used for alarms raised for one specific person (e.g. via
        ``notify.alarm_center_<person>``).
        """
        if not self.config.get("enabled", True):
            return

        if not ignore_quiet_hours and self.is_silenced(alarm.level):
            _LOGGER.debug(
                "Quiet hours: holding notification for %s (%s)", alarm.name, alarm.level
            )
            self._deferred[alarm.id] = True
            return

        if targets_override is not None:
            allowed: list[str] | None = targets_override
        else:
            rule = self.manager.get_rule(alarm.rule_id)
            allowed = rule.notify_targets if rule and rule.notify_targets else None

        prefix = "Still active" if reminder else LEVEL_TITLES.get(alarm.level, "Alarm")
        payload_title = f"{prefix}: {alarm.name}"
        payload_message = alarm.message or _default_message(alarm)
        tts_config = self.config.get("tts", {})
        tts_stream = tts_config.get("streams", {}).get(alarm.level, TTS_STREAM_OFF)
        tts_enabled = tts_config.get("enabled", False) and tts_stream != TTS_STREAM_OFF

        for target in self.config.get("targets", []):
            if not target.get("enabled", True):
                continue
            person = target.get("person")
            if allowed is not None and person not in allowed:
                continue
            min_level = target.get("min_level", LEVEL_WARNING)
            if LEVEL_SEVERITY.get(alarm.level, 0) < LEVEL_SEVERITY.get(min_level, 0):
                continue

            services = self.resolve_services(target)
            for service in services:
                await self._async_call(
                    service,
                    {
                        ATTR_TITLE: payload_title,
                        ATTR_MESSAGE: payload_message,
                        ATTR_DATA: {
                            "tag": f"{NOTIFY_TAG_PREFIX}{alarm.id}",
                            # One channel per level, so the level can be
                            # muted independently in the phone's own
                            # notification settings. Android creates the
                            # channel on first use with this importance -
                            # changing it later needs the user to clear the
                            # app's notification data once.
                            "channel": LEVEL_CHANNEL.get(alarm.level, "Alarm Center"),
                            "importance": LEVEL_IMPORTANCE.get(alarm.level, "default"),
                            "actions": [
                                {
                                    "action": f"{NOTIFY_ACK_ACTION_PREFIX}{alarm.id}",
                                    "title": "Kvittera",
                                }
                            ],
                        },
                    },
                )

            if tts_enabled and target.get("tts", False):
                for service in services:
                    await self._async_call(
                        service,
                        {
                            ATTR_MESSAGE: "TTS",
                            ATTR_DATA: {
                                "media_stream": tts_stream,
                                "tts_text": f"{payload_title}. {payload_message}",
                            },
                        },
                    )

    async def async_send_reminder(self, alarm: Alarm) -> None:
        """Re-send a still-active, unacknowledged alarm.

        The old notification is cleared first and the new one reuses the
        same tag, so the phone shows one current notification per alarm
        instead of an accumulating pile.
        """
        await self.async_clear_notification(alarm)
        await self.async_notify_new(alarm, reminder=True)

    async def async_send_digest(self, alarms: list[Alarm]) -> None:
        """One summary covering everything still active."""
        if not alarms or not self.config.get("enabled", True):
            return

        unacked = sum(1 for a in alarms if not a.acknowledged)
        worst = max(alarms, key=lambda a: a.severity)
        title = f"{len(alarms)} alarm(s) still active"
        lines = [
            f"{LEVEL_TITLES.get(a.level, a.level)}: {a.name}" for a in alarms[:10]
        ]
        if len(alarms) > 10:
            lines.append(f"…and {len(alarms) - 10} more")
        if unacked:
            lines.append(f"{unacked} not yet acknowledged")
        message = "\n".join(lines)

        for target in self.config.get("targets", []):
            if not target.get("enabled", True):
                continue
            min_level = target.get("min_level", LEVEL_WARNING)
            # The digest is addressed at the worst alarm in it, so a
            # notice-only digest doesn't wake someone who only wants errors.
            if LEVEL_SEVERITY.get(worst.level, 0) < LEVEL_SEVERITY.get(min_level, 0):
                continue
            for service in self.resolve_services(target):
                await self._async_call(
                    service,
                    {
                        ATTR_MESSAGE: "clear_notification",
                        ATTR_DATA: {"tag": NOTIFY_TAG_DIGEST},
                    },
                )
                await self._async_call(
                    service,
                    {
                        ATTR_TITLE: title,
                        ATTR_MESSAGE: message,
                        ATTR_DATA: {
                            "tag": NOTIFY_TAG_DIGEST,
                            "channel": LEVEL_CHANNEL.get(worst.level, "Alarm Center"),
                            "importance": LEVEL_IMPORTANCE.get(worst.level, "default"),
                        },
                    },
                )

    async def async_clear_notification(self, alarm: Alarm) -> None:
        """Remove the notification from the devices once acknowledged."""
        if not self.config.get("enabled", True):
            return
        for target in self.config.get("targets", []):
            if not target.get("enabled", True):
                continue
            for service in self.resolve_services(target):
                await self._async_call(
                    service,
                    {
                        ATTR_MESSAGE: "clear_notification",
                        ATTR_DATA: {"tag": f"{NOTIFY_TAG_PREFIX}{alarm.id}"},
                    },
                )

    async def _async_call(self, service: str, data: dict[str, Any]) -> None:
        if not self.hass.services.has_service(NOTIFY_DOMAIN, service):
            _LOGGER.warning("Notify service notify.%s is not available", service)
            return
        try:
            await self.hass.services.async_call(
                NOTIFY_DOMAIN, service, data, blocking=False
            )
        except Exception:  # noqa: BLE001 - a failing phone must not break alarms
            _LOGGER.exception("Could not notify via notify.%s", service)

    # -- target resolution -----------------------------------------------

    @callback
    def resolve_services(self, target: dict[str, Any]) -> list[str]:
        """Notify service names for a target, manual override wins."""
        manual = target.get("services")
        if manual:
            return list(manual)
        person = target.get("person")
        return self.resolve_person_services(person) if person else []

    @callback
    def resolve_person_services(self, person_entity_id: str) -> list[str]:
        """Find notify.mobile_app_* services for a person's devices."""
        state = self.hass.states.get(person_entity_id)
        if state is None:
            return []

        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        services: list[str] = []

        for tracker in state.attributes.get("device_trackers", []):
            entry = entity_registry.async_get(tracker)
            if entry is None or entry.device_id is None:
                continue
            device = device_registry.async_get(entry.device_id)
            if device is None:
                continue
            if not any(
                self.hass.config_entries.async_get_entry(entry_id)
                and self.hass.config_entries.async_get_entry(entry_id).domain
                == MOBILE_APP_DOMAIN
                for entry_id in device.config_entries
            ):
                continue
            service = f"{MOBILE_APP_DOMAIN}_{slugify(device.name_by_user or device.name)}"
            if service not in services:
                services.append(service)
        return services

    @callback
    def available_targets(self) -> list[dict[str, Any]]:
        """Every person with the notify services we could find, for the panel."""
        result = []
        for state in self.hass.states.async_all("person"):
            result.append(
                {
                    "person": state.entity_id,
                    "name": state.name,
                    "services": self.resolve_person_services(state.entity_id),
                }
            )
        return result

    # -- incoming actions ------------------------------------------------

    async def _handle_mobile_action(self, event: Event) -> None:
        """Acknowledge from the notification action button."""
        action = event.data.get("action", "")
        if not action.startswith(NOTIFY_ACK_ACTION_PREFIX):
            return
        alarm_id = action[len(NOTIFY_ACK_ACTION_PREFIX) :]
        user_id = event.context.user_id if event.context else None
        user_name = None
        if user_id:
            user = await self.hass.auth.async_get_user(user_id)
            user_name = user.name if user else None
        await self.manager.async_acknowledge(
            alarm_id,
            user_id=user_id,
            user_name=user_name or "Mobilapp",
            context=event.context,
        )


def _default_message(alarm: Alarm) -> str:
    """Fallback notification body."""
    if alarm.entity_id:
        return f"{alarm.name} ({alarm.entity_id})"
    return alarm.name
