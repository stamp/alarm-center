"""WebSocket API for the Alarm Center panel."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DEFAULT_HISTORY_LIMIT, DOMAIN, SIGNAL_UPDATE

_LOGGER = logging.getLogger(__name__)


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every command once, at integration setup."""
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_acknowledge)
    websocket_api.async_register_command(hass, ws_acknowledge_all)
    websocket_api.async_register_command(hass, ws_history)
    websocket_api.async_register_command(hass, ws_rules)
    websocket_api.async_register_command(hass, ws_save_rule)
    websocket_api.async_register_command(hass, ws_set_rule_enabled)
    websocket_api.async_register_command(hass, ws_delete_rule)
    websocket_api.async_register_command(hass, ws_rules_trash)
    websocket_api.async_register_command(hass, ws_rules_restore)
    websocket_api.async_register_command(hass, ws_rules_purge)
    websocket_api.async_register_command(hass, ws_get_config)
    websocket_api.async_register_command(hass, ws_save_config)
    websocket_api.async_register_command(hass, ws_notify_targets)


@callback
def _data(hass: HomeAssistant):
    """Return the single runtime data object."""
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        return None
    return next(iter(entries.values()))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(hass, connection, msg) -> None:
    """Send the current alarm list and push every change after that."""
    data = _data(hass)
    if data is None:
        connection.send_error(msg["id"], "not_loaded", "Alarm Center is not loaded")
        return

    @callback
    def _forward() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], data.manager.snapshot())
        )

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_UPDATE, _forward
    )
    connection.send_result(msg["id"])
    _forward()


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/acknowledge", vol.Required("alarm_id"): str}
)
@websocket_api.async_response
async def ws_acknowledge(hass, connection, msg) -> None:
    """Acknowledge one alarm, recording the logged in user."""
    data = _data(hass)
    user = connection.user
    alarm = await data.manager.async_acknowledge(
        msg["alarm_id"],
        user_id=user.id if user else None,
        user_name=user.name if user else None,
        context=connection.context(msg),
    )
    if alarm is None:
        connection.send_error(msg["id"], "not_found", "No such open alarm")
        return
    connection.send_result(msg["id"], alarm.as_dict())


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/acknowledge_all"})
@websocket_api.async_response
async def ws_acknowledge_all(hass, connection, msg) -> None:
    """Acknowledge every open alarm."""
    data = _data(hass)
    user = connection.user
    count = await data.manager.async_acknowledge_all(
        user_id=user.id if user else None,
        user_name=user.name if user else None,
        context=connection.context(msg),
    )
    connection.send_result(msg["id"], {"acknowledged": count})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/history",
        vol.Optional("limit", default=DEFAULT_HISTORY_LIMIT): int,
        vol.Optional("offset", default=0): int,
    }
)
@websocket_api.async_response
async def ws_history(hass, connection, msg) -> None:
    """Read archived alarms, newest first."""
    data = _data(hass)
    records = await data.store.async_read_history(
        limit=min(msg["limit"], 500), offset=msg["offset"]
    )
    connection.send_result(msg["id"], {"history": records})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rules"})
@callback
def ws_rules(hass, connection, msg) -> None:
    """List all rules."""
    data = _data(hass)
    connection.send_result(msg["id"], {"rules": data.engine.as_list()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rules/save", vol.Required("rule"): dict}
)
@websocket_api.async_response
async def ws_save_rule(hass, connection, msg) -> None:
    """Create or update a rule."""
    data = _data(hass)
    rule = dict(msg["rule"])
    for field in ("on_activate", "on_acknowledge", "on_clear"):
        if rule.get(field):
            try:
                rule[field] = cv.SCRIPT_SCHEMA(rule[field])
            except vol.Invalid as err:
                connection.send_error(
                    msg["id"], "invalid_actions", f"{field}: {err}"
                )
                return
    try:
        saved = await data.engine.async_save_rule(rule)
    except (KeyError, ValueError) as err:
        connection.send_error(msg["id"], "invalid_rule", str(err))
        return
    connection.send_result(msg["id"], saved.as_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/rules/set_enabled",
        vol.Required("rule_id"): str,
        vol.Required("enabled"): bool,
    }
)
@websocket_api.async_response
async def ws_set_rule_enabled(hass, connection, msg) -> None:
    """Switch a rule on or off."""
    data = _data(hass)
    rule = await data.engine.async_set_enabled(msg["rule_id"], msg["enabled"])
    if rule is None:
        connection.send_error(msg["id"], "not_found", "No such rule")
        return
    connection.send_result(msg["id"], rule.as_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rules/delete", vol.Required("rule_id"): str}
)
@websocket_api.async_response
async def ws_delete_rule(hass, connection, msg) -> None:
    """Delete a rule. It moves to the trash and can be restored later."""
    data = _data(hass)
    await data.engine.async_delete_rule(msg["rule_id"])
    connection.send_result(msg["id"], {"deleted": msg["rule_id"]})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/rules/trash"})
@callback
def ws_rules_trash(hass, connection, msg) -> None:
    """List deleted rules that can still be restored."""
    data = _data(hass)
    connection.send_result(msg["id"], {"trash": data.engine.trash_as_list()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rules/restore", vol.Required("rule_id"): str}
)
@websocket_api.async_response
async def ws_rules_restore(hass, connection, msg) -> None:
    """Restore a deleted rule from the trash."""
    data = _data(hass)
    rule = await data.engine.async_restore_rule(msg["rule_id"])
    if rule is None:
        connection.send_error(msg["id"], "not_found", "No such rule in the trash")
        return
    connection.send_result(msg["id"], rule.as_dict())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/rules/purge", vol.Required("rule_id"): str}
)
@websocket_api.async_response
async def ws_rules_purge(hass, connection, msg) -> None:
    """Permanently remove a rule from the trash."""
    data = _data(hass)
    await data.engine.async_purge_rule(msg["rule_id"])
    connection.send_result(msg["id"], {"purged": msg["rule_id"]})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/config"})
@callback
def ws_get_config(hass, connection, msg) -> None:
    """Return the settings shown in the panel."""
    data = _data(hass)
    config: dict[str, Any] = {
        key: value for key, value in data.store.config.items() if key != "rules"
    }
    connection.send_result(msg["id"], config)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/config/save", vol.Required("config"): dict}
)
@websocket_api.async_response
async def ws_save_config(hass, connection, msg) -> None:
    """Update settings. Rules are managed through their own commands."""
    data = _data(hass)
    incoming = {k: v for k, v in msg["config"].items() if k != "rules"}
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(data.store.config.get(key), dict):
            data.store.config[key].update(value)
        else:
            data.store.config[key] = value
    data.store.async_save_config(immediate=True)
    await data.engine.async_sync_auto_rules()
    # Digest time and quiet-hours end are timers, so they have to be
    # re-registered for a changed time to take effect.
    await data.reminders.async_reload()
    connection.send_result(msg["id"], {"saved": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/notify_targets"})
@callback
def ws_notify_targets(hass, connection, msg) -> None:
    """People we can notify, with auto-detected notify services."""
    data = _data(hass)
    connection.send_result(
        msg["id"], {"targets": data.notifier.available_targets()}
    )
