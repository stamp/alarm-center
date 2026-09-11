"""Alarm Center as a notification target.

Registers services under the ``notify`` domain, the same way classic notify
platforms do, so they show up anywhere Home Assistant lets you pick a notify
service (automations, scripts, blueprints):

* ``notify.alarm_center`` - a global target. Sending a message to it raises
  an alarm (default level ``warning``, overridable), which appears in the
  alarm list and can be acknowledged immediately like any other alarm.
* ``notify.alarm_center_<person>`` - one per ``person.*`` entity. Sending a
  message forwards it to that person's resolved devices, so automations can
  address "Stamp" instead of a specific phone. Optionally also raises an
  alarm scoped to just that person.

Both reuse the "manual:" key namespace also used by the ``alarm_center.
raise_alarm`` / ``clear_alarm`` services, so the same key reactivates the
same alarm regardless of which route created it.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components.notify import ATTR_DATA, ATTR_MESSAGE, ATTR_TITLE
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import slugify

from .const import LEVELS

_LOGGER = logging.getLogger(__name__)

NOTIFY_DOMAIN = "notify"
GLOBAL_SERVICE = "alarm_center"
PERSON_SERVICE_PREFIX = "alarm_center_"
SYNC_INTERVAL_MINUTES = 10
DEFAULT_LEVEL = "warning"

# Home Assistant only renders a service's YAML/UI form from a services.yaml
# in *that* service's own domain, so a service registered here under
# "notify" gets no such form. This schema at least turns a malformed call
# into a clear error instead of a silent no-op.
NOTIFY_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_DATA): dict,
    },
    extra=vol.ALLOW_EXTRA,
)


class NotifyTargets:
    """Owns the notify.* services this integration exposes."""

    def __init__(self, hass: HomeAssistant, manager, notifier) -> None:
        """Set up with references to the alarm manager and notifier."""
        self.hass = hass
        self.manager = manager
        self.notifier = notifier
        self._person_services: set[str] = set()
        self._unsub: list[CALLBACK_TYPE] = []

    async def async_setup(self) -> None:
        """Register the global service and start tracking persons."""
        self.hass.services.async_register(
            NOTIFY_DOMAIN,
            GLOBAL_SERVICE,
            self._handle_global,
            schema=NOTIFY_SERVICE_SCHEMA,
        )

        self._unsub.append(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._handle_started
            )
        )
        self._unsub.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_updated
            )
        )
        self._unsub.append(
            async_track_time_interval(
                self.hass,
                self._handle_periodic_sync,
                timedelta(minutes=SYNC_INTERVAL_MINUTES),
            )
        )

        if self.hass.is_running:
            self._sync_person_services()

    async def async_unload(self) -> None:
        """Remove every registered service and stop listening."""
        for cancel in self._unsub:
            cancel()
        self._unsub.clear()
        self.hass.services.async_remove(NOTIFY_DOMAIN, GLOBAL_SERVICE)
        for service in list(self._person_services):
            self.hass.services.async_remove(NOTIFY_DOMAIN, service)
        self._person_services.clear()

    # -- keeping the per-person services in sync -------------------------

    async def _handle_started(self, _event: Event) -> None:
        self._sync_person_services()

    async def _handle_registry_updated(self, event: Event) -> None:
        entity_id = event.data.get("entity_id", "")
        if entity_id.startswith("person."):
            self._sync_person_services()

    async def _handle_periodic_sync(self, _now) -> None:
        self._sync_person_services()

    def _sync_person_services(self) -> None:
        """Register a service for every current person, drop stale ones."""
        wanted: dict[str, str] = {}  # service name -> person entity_id
        for state in self.hass.states.async_all("person"):
            object_id = state.entity_id.split(".", 1)[1]
            wanted[f"{PERSON_SERVICE_PREFIX}{slugify(object_id)}"] = state.entity_id

        for service, person_entity_id in wanted.items():
            if service in self._person_services:
                continue
            self.hass.services.async_register(
                NOTIFY_DOMAIN,
                service,
                self._make_person_handler(person_entity_id),
                schema=NOTIFY_SERVICE_SCHEMA,
            )
            self._person_services.add(service)
            _LOGGER.debug(
                "Registered notify.%s for %s", service, person_entity_id
            )

        stale = self._person_services - set(wanted)
        for service in stale:
            self.hass.services.async_remove(NOTIFY_DOMAIN, service)
            self._person_services.discard(service)
            _LOGGER.debug("Removed notify.%s (person no longer exists)", service)

    # -- handlers ----------------------------------------------------------

    async def _handle_global(self, call: ServiceCall) -> None:
        """notify.alarm_center service - parse the call and delegate."""
        message = call.data.get(ATTR_MESSAGE, "")
        title = call.data.get(ATTR_TITLE)
        extra = call.data.get(ATTR_DATA) or {}
        await self.async_handle_global(message, title, extra)

    async def async_handle_global(
        self, message: str, title: str | None, extra: dict[str, Any]
    ) -> None:
        """Raise (or clear) a manual alarm.

        Shared by the ``notify.alarm_center`` service and the entity-based
        ``notify`` platform's global entity - ``extra`` is only populated by
        the service route, since the entity platform's ``async_send_message``
        only carries message and title.
        """
        key = extra.get("key") or slugify(title or message)[:60] or "alarm"
        alarm_key = f"manual:{key}"

        if extra.get("clear"):
            self.manager.clear_alarm(alarm_key)
            return

        level = extra.get("level", DEFAULT_LEVEL)
        if level not in LEVELS:
            _LOGGER.warning(
                "notify.alarm_center: unknown level %r, using %s", level, DEFAULT_LEVEL
            )
            level = DEFAULT_LEVEL

        self.manager.raise_alarm(
            alarm_key,
            name=title or message,
            level=level,
            message=message if title else None,
            notify=extra.get("notify", True),
        )

    def _make_person_handler(self, person_entity_id: str):
        async def _handle(call: ServiceCall) -> None:
            message = call.data.get(ATTR_MESSAGE, "")
            title = call.data.get(ATTR_TITLE)
            extra = dict(call.data.get(ATTR_DATA) or {})
            await self.async_handle_person(person_entity_id, message, title, extra)

        return _handle

    async def async_handle_person(
        self,
        person_entity_id: str,
        message: str,
        title: str | None,
        extra: dict[str, Any],
    ) -> None:
        """Forward to a person's devices, or raise a person-scoped alarm.

        Shared by ``notify.alarm_center_<person>`` and the entity-based
        ``notify`` platform's per-person entities.
        """
        extra = dict(extra)

        if extra.pop("alarm", False):
            key = extra.pop("key", None) or slugify(
                f"{person_entity_id}:{title or message}"
            )[:60]
            alarm_key = f"manual:{key}"
            level = extra.pop("level", DEFAULT_LEVEL)
            if level not in LEVELS:
                _LOGGER.warning(
                    "notify.%s%s: unknown level %r, using %s",
                    PERSON_SERVICE_PREFIX,
                    person_entity_id.split(".", 1)[1],
                    level,
                    DEFAULT_LEVEL,
                )
                level = DEFAULT_LEVEL
            self.manager.raise_alarm(
                alarm_key,
                name=title or message,
                level=level,
                message=message if title else None,
                notify=True,
                notify_targets=[person_entity_id],
            )
            return

        services = self.notifier.resolve_person_services(person_entity_id)
        if not services:
            _LOGGER.warning(
                "notify.%s%s: no notify service found for %s (no mobile_app device?)",
                PERSON_SERVICE_PREFIX,
                person_entity_id.split(".", 1)[1],
                person_entity_id,
            )
            return

        payload: dict[str, Any] = {ATTR_MESSAGE: message}
        if title:
            payload[ATTR_TITLE] = title
        if extra:
            payload[ATTR_DATA] = extra

        for service in services:
            await self.hass.services.async_call(
                NOTIFY_DOMAIN, service, payload, blocking=False
            )
