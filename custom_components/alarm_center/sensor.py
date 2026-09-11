"""Counter sensors for Alarm Center."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the counter sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlarmCountSensor(data, entry, "open", "Open alarms", "mdi:format-list-bulleted"),
            AlarmCountSensor(data, entry, "active", "Active alarms", "mdi:alarm-light"),
            AlarmCountSensor(
                data, entry, "unacknowledged", "Unacknowledged alarms", "mdi:bell-ring"
            ),
            HighestLevelSensor(data, entry),
        ]
    )


class AlarmCenterEntity:
    """Shared plumbing: one device, push updates over the dispatcher."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data, entry: ConfigEntry) -> None:
        """Store the runtime data."""
        self._data = data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Alarm Center",
            manufacturer="Alarm Center",
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to alarm changes."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_UPDATE, self._handle_update)
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class AlarmCountSensor(AlarmCenterEntity, SensorEntity):
    """Number of alarms in a given state."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, data, entry: ConfigEntry, kind: str, name: str, icon: str) -> None:
        """Set up one counter."""
        super().__init__(data, entry)
        self._kind = kind
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{kind}"

    @property
    def native_value(self) -> int:
        """Current count."""
        return self._data.manager.counts()[self._kind]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the alarm list so it can be used in dashboards."""
        if self._kind != "open":
            return {}
        return {"alarms": [a.as_dict() for a in self._data.manager.book.open_alarms]}


class HighestLevelSensor(AlarmCenterEntity, SensorEntity):
    """Most severe level among the active alarms."""

    _attr_name = "Highest alarm level"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, data, entry: ConfigEntry) -> None:
        """Set up the sensor."""
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_highest_level"

    @property
    def native_value(self) -> str:
        """Highest active level, or 'none'."""
        return self._data.manager.highest_level() or "none"
