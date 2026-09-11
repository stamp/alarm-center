"""The Alarm Center integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from . import websocket_api
from .const import (
    DOMAIN,
    LEVELS,
    PANEL_COMPONENT_NAME,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    SERVICE_ACKNOWLEDGE,
    SERVICE_ACKNOWLEDGE_ALL,
    SERVICE_CLEAR,
    SERVICE_RAISE,
    STATIC_URL,
    VERSION,
)
from .manager import AlarmManager
from .notifier import Notifier
from .notify_target import NotifyTargets
from .reminders import ReminderScheduler
from .rules import RuleEngine
from .store import AlarmCenterStore

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.NOTIFY, Platform.SENSOR]

RAISE_SCHEMA = vol.Schema(
    {
        vol.Required("key"): cv.string,
        vol.Required("name"): cv.string,
        vol.Optional("level", default="warning"): vol.In(LEVELS),
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("message"): cv.string,
        vol.Optional("notify", default=True): cv.boolean,
    }
)
CLEAR_SCHEMA = vol.Schema({vol.Required("key"): cv.string})
ACK_SCHEMA = vol.Schema({vol.Required("alarm_id"): cv.string})


@dataclass
class AlarmCenterData:
    """Everything the integration keeps in memory."""

    store: AlarmCenterStore
    manager: AlarmManager
    engine: RuleEngine
    notifier: Notifier
    notify_targets: NotifyTargets
    reminders: ReminderScheduler


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alarm Center from a config entry."""
    store = AlarmCenterStore(hass)
    config = await store.async_load_config()

    manager = AlarmManager(hass, store, config)
    await manager.async_load()

    engine = RuleEngine(hass, store, manager)
    notifier = Notifier(hass, store, manager)
    manager.notifier = notifier

    await engine.async_setup()
    await notifier.async_setup()

    notify_targets = NotifyTargets(hass, manager, notifier)
    await notify_targets.async_setup()

    reminders = ReminderScheduler(hass, store, manager, notifier)
    await reminders.async_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = AlarmCenterData(
        store=store,
        manager=manager,
        engine=engine,
        notifier=notifier,
        notify_targets=notify_targets,
        reminders=reminders,
    )

    websocket_api.async_register(hass)
    await _async_register_panel(hass)
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Evaluate everything once so restored alarms match reality again.
    engine.async_evaluate_all()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data: AlarmCenterData = hass.data[DOMAIN].pop(entry.entry_id)

    await data.engine.async_unload()
    await data.notifier.async_unload()
    await data.notify_targets.async_unload()
    await data.reminders.async_unload()
    await data.manager.async_shutdown()

    if not hass.data[DOMAIN]:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        # Home Assistant has no matching remove for add_extra_js_url. It stays
        # registered until Home Assistant restarts; harmless since the card
        # is only rendered where a dashboard actually uses it, and the
        # integration is single_config_entry so this only happens once.
        for service in (
            SERVICE_RAISE,
            SERVICE_CLEAR,
            SERVICE_ACKNOWLEDGE,
            SERVICE_ACKNOWLEDGE_ALL,
        ):
            hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Serve the panel and card JS, add the panel to the sidebar."""
    already_set_up = PANEL_URL_PATH in hass.data.get("frontend_panels", {})

    if not already_set_up:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    STATIC_URL,
                    hass.config.path(f"custom_components/{DOMAIN}/frontend"),
                    cache_headers=False,
                )
            ]
        )
        await panel_custom.async_register_panel(
            hass,
            webcomponent_name=PANEL_COMPONENT_NAME,
            frontend_url_path=PANEL_URL_PATH,
            # The version query busts the browser cache after an update.
            module_url=f"{STATIC_URL}/panel.js?v={VERSION}",
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
            config={"version": VERSION},
        )

    # Loads the dashboard card on every page, so it works without adding a
    # manual resource in Settings > Dashboards > Resources.
    frontend.add_extra_js_url(hass, f"{STATIC_URL}/alarm-center-card.js?v={VERSION}")


@callback
def _async_register_services(hass: HomeAssistant) -> None:
    """Register the services. Also usable from automations and scripts."""
    if hass.services.has_service(DOMAIN, SERVICE_RAISE):
        return

    def _first_data() -> AlarmCenterData:
        return next(iter(hass.data[DOMAIN].values()))

    async def _async_user(call: ServiceCall) -> tuple[str | None, str | None]:
        user_id = call.context.user_id
        if not user_id:
            return None, "Automation"
        user = await hass.auth.async_get_user(user_id)
        return user_id, user.name if user else None

    async def handle_raise(call: ServiceCall) -> None:
        data = _first_data()
        data.manager.raise_alarm(
            f"manual:{call.data['key']}",
            name=call.data["name"],
            level=call.data["level"],
            entity_id=call.data.get("entity_id"),
            message=call.data.get("message"),
            notify=call.data["notify"],
        )

    async def handle_clear(call: ServiceCall) -> None:
        _first_data().manager.clear_alarm(f"manual:{call.data['key']}")

    async def handle_acknowledge(call: ServiceCall) -> None:
        user_id, user_name = await _async_user(call)
        await _first_data().manager.async_acknowledge(
            call.data["alarm_id"],
            user_id=user_id,
            user_name=user_name,
            context=call.context,
        )

    async def handle_acknowledge_all(call: ServiceCall) -> None:
        user_id, user_name = await _async_user(call)
        await _first_data().manager.async_acknowledge_all(
            user_id=user_id, user_name=user_name, context=call.context
        )

    hass.services.async_register(DOMAIN, SERVICE_RAISE, handle_raise, RAISE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR, handle_clear, CLEAR_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_ACKNOWLEDGE, handle_acknowledge, ACK_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_ACKNOWLEDGE_ALL, handle_acknowledge_all
    )
