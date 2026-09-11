"""Summary binary sensors for Alarm Center.

These use device class ``problem``, but the rule engine skips entities that
belong to this integration, so they never generate alarms about themselves.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .sensor import AlarmCenterEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the summary binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AlarmFlagSensor(data, entry, "any_active", "Alarm active"),
            AlarmFlagSensor(data, entry, "any_unacknowledged", "Unacknowledged alarm"),
        ]
    )


class AlarmFlagSensor(AlarmCenterEntity, BinarySensorEntity):
    """True when there is at least one alarm in the given state."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, data, entry: ConfigEntry, kind: str, name: str) -> None:
        """Set up one flag."""
        super().__init__(data, entry)
        self._kind = kind
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{kind}"

    @property
    def is_on(self) -> bool:
        """Whether the flag is set."""
        counts = self._data.manager.counts()
        if self._kind == "any_active":
            return counts["active"] > 0
        return counts["unacknowledged"] > 0
