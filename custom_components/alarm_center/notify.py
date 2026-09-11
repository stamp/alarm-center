"""Entity-based notify platform for Alarm Center.

Home Assistant has two ways for an integration to be a notify target: the
classic ``notify.<service>`` services (see ``notify_target.py``) and the
newer entity platform (``NotifyEntity``), which shows up as regular
``notify.*`` entities and in target pickers. This registers the same two
targets - the global one and one per person - through the entity platform,
so both styles work side by side.

The entity platform's ``async_send_message`` only carries a message and an
optional title, unlike the service route which also accepts a free-form
``data`` dict. So the entity route always behaves like the plain, unscoped
case (raise/forward with defaults); anyone who needs a specific level, a
stable key, to clear an alarm, or to scope a person notification into an
alarm should keep using the ``notify.alarm_center`` / ``notify.
alarm_center_<person>`` services from ``notify_target.py``, which remain the
authority both routes ultimately call into.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .notify_target import SYNC_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the global notify entity and one per current/future person."""
    data = hass.data[DOMAIN][entry.entry_id]
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Alarm Center",
        manufacturer="Alarm Center",
        entry_type=dr.DeviceEntryType.SERVICE,
    )

    async_add_entities(
        [AlarmCenterGlobalNotify(data.notify_targets, entry, device_info)]
    )

    known: dict[str, AlarmCenterPersonNotify] = {}

    @callback
    def _sync_persons() -> None:
        wanted = {state.entity_id: state for state in hass.states.async_all("person")}

        new_entities = [
            AlarmCenterPersonNotify(data.notify_targets, entry, device_info, state)
            for entity_id, state in wanted.items()
            if entity_id not in known
        ]
        for entity in new_entities:
            known[entity.person_entity_id] = entity
        if new_entities:
            async_add_entities(new_entities)

        for entity_id in set(known) - set(wanted):
            hass.async_create_task(known.pop(entity_id).async_remove(force_remove=True))

    if hass.is_running:
        _sync_persons()

    @callback
    def _handle_started(_event: Event) -> None:
        _sync_persons()

    @callback
    def _handle_registry_updated(event: Event) -> None:
        if event.data.get("entity_id", "").startswith("person."):
            _sync_persons()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _handle_started)
    )
    entry.async_on_unload(
        hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _handle_registry_updated)
    )
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            lambda _now: _sync_persons(),
            timedelta(minutes=SYNC_INTERVAL_MINUTES),
        )
    )


class AlarmCenterGlobalNotify(NotifyEntity):
    """Mirrors notify.alarm_center: sending a message raises an alarm.

    Left without its own name (``_attr_name = None``) so, as the sole entity
    on the "Alarm Center" device, it takes the device's name - which makes
    its auto-generated entity_id ``notify.alarm_center``, matching the
    legacy service of the same name.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, targets, entry: ConfigEntry, device_info: DeviceInfo) -> None:
        """Set up the global notify entity."""
        self._targets = targets
        self._attr_unique_id = f"{entry.entry_id}_notify_global"
        self._attr_device_info = device_info

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Raise a manual alarm with the default level."""
        await self._targets.async_handle_global(message, title, {})


class AlarmCenterPersonNotify(NotifyEntity):
    """Mirrors notify.alarm_center_<person>: forwards to that person.

    Named after the person only - combined with the shared device name this
    reads as "Alarm Center <name>" and, again, its auto-generated entity_id
    ends up matching the legacy ``notify.alarm_center_<person>`` service.
    """

    _attr_has_entity_name = True
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(
        self,
        targets,
        entry: ConfigEntry,
        device_info: DeviceInfo,
        person_state: State,
    ) -> None:
        """Set up the per-person notify entity."""
        self._targets = targets
        self.person_entity_id = person_state.entity_id
        object_id = self.person_entity_id.split(".", 1)[1]
        self._attr_unique_id = f"{entry.entry_id}_notify_{object_id}"
        self._attr_name = person_state.name
        self._attr_device_info = device_info

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Forward the message to this person's devices."""
        await self._targets.async_handle_person(
            self.person_entity_id, message, title, {}
        )
