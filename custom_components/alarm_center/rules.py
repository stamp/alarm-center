"""Rule storage, evaluation and auto-generation.

Every alarm source in Alarm Center is a rule, including the ones generated
automatically for ``binary_sensor`` entities with device class ``problem``.
That way the panel always shows what is actually being monitored, and any
rule can be switched off individually.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_FRIENDLY_NAME,
    EVENT_HOMEASSISTANT_STARTED,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    TrackTemplate,
    async_call_later,
    async_track_state_change_event,
    async_track_template_result,
    async_track_time_interval,
)
from homeassistant.helpers.template import Template
from homeassistant.util import slugify

from .const import (
    AUTO_RULE_PREFIX,
    AUTO_SYNC_INTERVAL_MINUTES,
    DEFAULT_AUTO_RULE_LEVEL,
    DOMAIN,
    KIND_PROBLEM,
    KIND_TEMPLATE,
)
from .evaluation import as_bool, evaluate_condition
from .models import Rule, utcnow

_LOGGER = logging.getLogger(__name__)

TRASH_LIMIT = 50


class RuleEngine:
    """Holds the rules and turns entity changes into alarm transitions."""

    def __init__(self, hass: HomeAssistant, store, manager) -> None:
        """Set up the engine."""
        self.hass = hass
        self.store = store
        self.manager = manager
        self.rules: dict[str, Rule] = {}
        self._unsub_states: CALLBACK_TYPE | None = None
        self._unsub_templates: list[CALLBACK_TYPE] = []
        self._unsub_misc: list[CALLBACK_TYPE] = []
        self._pending: dict[str, CALLBACK_TYPE] = {}

    @property
    def config(self) -> dict[str, Any]:
        """Live config dict from the store."""
        return self.store.config

    # -- setup / teardown ------------------------------------------------

    async def async_setup(self) -> None:
        """Load rules and start listening."""
        for data in self.config.get("rules", []):
            try:
                rule = Rule.from_dict(data)
            except (KeyError, ValueError):
                _LOGGER.warning("Skipping malformed rule: %s", data)
                continue
            self.rules[rule.id] = rule

        self.manager.get_rule = self.get_rule

        self._unsub_misc.append(
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._handle_started
            )
        )
        self._unsub_misc.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_registry_updated
            )
        )
        self._unsub_misc.append(
            async_track_time_interval(
                self.hass,
                self._handle_periodic_sync,
                timedelta(minutes=AUTO_SYNC_INTERVAL_MINUTES),
            )
        )

        if self.hass.is_running:
            await self.async_sync_auto_rules()
        self._resubscribe()

    async def async_unload(self) -> None:
        """Stop all listeners."""
        self._unsubscribe()
        for cancel in self._unsub_misc:
            cancel()
        self._unsub_misc.clear()
        for cancel in self._pending.values():
            cancel()
        self._pending.clear()

    # -- rule CRUD -------------------------------------------------------

    @callback
    def get_rule(self, rule_id: str | None) -> Rule | None:
        """Look up a rule by id."""
        return self.rules.get(rule_id) if rule_id else None

    @callback
    def as_list(self) -> list[dict[str, Any]]:
        """All rules, auto-generated ones last."""
        return [
            rule.as_dict()
            for rule in sorted(self.rules.values(), key=lambda r: (r.auto, r.name.lower()))
        ]

    async def async_save_rule(self, data: dict[str, Any]) -> Rule:
        """Create or update a rule and re-evaluate it immediately."""
        if not data.get("id"):
            data["id"] = self._unique_id(data.get("name") or "rule")
        rule = Rule.from_dict(data)
        self.rules[rule.id] = rule
        await self._async_persist()
        self._resubscribe()
        if rule.enabled:
            self._evaluate_rule_now(rule)
        else:
            # Administrative clear: the fault did not go away, so the
            # rule's on_clear actions must not run.
            self.manager.clear_alarm(rule.alarm_key, run_actions=False)
        return rule

    async def async_set_enabled(self, rule_id: str, enabled: bool) -> Rule | None:
        """Turn a rule on or off."""
        rule = self.rules.get(rule_id)
        if rule is None:
            return None
        rule.enabled = enabled
        await self._async_persist()
        self._resubscribe()
        if enabled:
            self._evaluate_rule_now(rule)
        else:
            self._cancel_pending(rule.id)
            self.manager.clear_alarm(rule.alarm_key, run_actions=False)
        return rule

    async def async_delete_rule(self, rule_id: str) -> None:
        """Delete a rule. It moves to the trash, so it can be restored.

        Auto rules are also remembered in ``auto_rules.ignored`` so they are
        not immediately recreated by the next sync - that entry is removed
        again on restore.
        """
        rule = self.rules.pop(rule_id, None)
        if rule is None:
            return
        self._cancel_pending(rule_id)
        self.manager.clear_alarm(rule.alarm_key, run_actions=False)
        if rule.auto and rule.source_entity_id:
            ignored = self.config["auto_rules"].setdefault("ignored", [])
            if rule.source_entity_id not in ignored:
                ignored.append(rule.source_entity_id)

        trashed = rule.as_dict()
        trashed["deleted_at"] = utcnow().isoformat()
        trash = self.config.setdefault("trash", [])
        trash.insert(0, trashed)
        del trash[TRASH_LIMIT:]

        await self._async_persist()
        self._resubscribe()

    async def async_restore_rule(self, rule_id: str) -> Rule | None:
        """Bring a deleted rule back from the trash."""
        trash = self.config.setdefault("trash", [])
        index = next((i for i, r in enumerate(trash) if r.get("id") == rule_id), None)
        if index is None:
            return None
        data = dict(trash.pop(index))
        data.pop("deleted_at", None)

        try:
            rule = Rule.from_dict(data)
        except (KeyError, ValueError):
            _LOGGER.warning("Could not restore malformed rule from trash: %s", data)
            await self._async_persist()
            return None

        # Make it unique again in case a new rule has since taken its id.
        if rule.id in self.rules:
            rule.id = self._unique_id(rule.id)

        self.rules[rule.id] = rule
        if rule.auto and rule.source_entity_id:
            ignored = self.config["auto_rules"].setdefault("ignored", [])
            if rule.source_entity_id in ignored:
                ignored.remove(rule.source_entity_id)

        await self._async_persist()
        self._resubscribe()
        if rule.enabled:
            self._evaluate_rule_now(rule)
        return rule

    async def async_purge_rule(self, rule_id: str) -> None:
        """Permanently remove a rule from the trash. Cannot be undone."""
        trash = self.config.setdefault("trash", [])
        remaining = [r for r in trash if r.get("id") != rule_id]
        if len(remaining) == len(trash):
            return
        self.config["trash"] = remaining
        await self._async_persist()

    @callback
    def trash_as_list(self) -> list[dict[str, Any]]:
        """Deleted rules, newest first - already stored in that order."""
        return list(self.config.get("trash", []))

    def _unique_id(self, base: str) -> str:
        slug = slugify(base) or "rule"
        candidate = slug
        index = 2
        while candidate in self.rules:
            candidate = f"{slug}_{index}"
            index += 1
        return candidate

    async def _async_persist(self) -> None:
        self.config["rules"] = [rule.as_dict() for rule in self.rules.values()]
        self.store.async_save_config()

    # -- auto rules ------------------------------------------------------

    async def async_sync_auto_rules(self) -> int:
        """Create rules for problem entities that do not have one yet.

        Runs at startup, whenever the entity registry changes and on a timer,
        so new problem entities are picked up without a restart.
        """
        auto_config = self.config.get("auto_rules", {})
        if not auto_config.get("enabled", True):
            return 0

        ignored = set(auto_config.get("ignored", []))
        known = {
            rule.source_entity_id for rule in self.rules.values() if rule.source_entity_id
        }
        registry = er.async_get(self.hass)
        created = 0

        for state in self.hass.states.async_all("binary_sensor"):
            entity_id = state.entity_id
            if entity_id in known or entity_id in ignored:
                continue
            if state.attributes.get(ATTR_DEVICE_CLASS) != BinarySensorDeviceClass.PROBLEM:
                continue
            # Never monitor our own summary entities - that would loop.
            entry = registry.async_get(entity_id)
            if entry is not None and entry.platform == DOMAIN:
                continue

            rule = Rule(
                id=self._unique_id(f"{AUTO_RULE_PREFIX}{entity_id}"),
                name=state.attributes.get(ATTR_FRIENDLY_NAME) or entity_id,
                kind=KIND_PROBLEM,
                level=auto_config.get("default_level", DEFAULT_AUTO_RULE_LEVEL),
                enabled=auto_config.get("start_enabled", True),
                entity_id=entity_id,
                auto=True,
                source_entity_id=entity_id,
            )
            self.rules[rule.id] = rule
            known.add(entity_id)
            created += 1

        if created:
            _LOGGER.info("Created %s rule(s) for new problem entities", created)
            await self._async_persist()
            self._resubscribe()
            for rule in self.rules.values():
                if rule.auto and rule.enabled:
                    self._evaluate_rule_now(rule)
        return created

    async def _handle_started(self, _event: Event) -> None:
        await self.async_sync_auto_rules()
        self._resubscribe()
        self.async_evaluate_all()

    async def _handle_registry_updated(self, event: Event) -> None:
        if event.data.get("action") not in ("create", "update"):
            return
        entity_id = event.data.get("entity_id", "")
        if not entity_id.startswith("binary_sensor."):
            return
        await self.async_sync_auto_rules()

    async def _handle_periodic_sync(self, _now) -> None:
        await self.async_sync_auto_rules()

    # -- evaluation ------------------------------------------------------

    @callback
    def _resubscribe(self) -> None:
        """Rebuild the entity and template subscriptions."""
        self._unsubscribe()

        entity_ids = {
            rule.entity_id
            for rule in self.rules.values()
            if rule.enabled and rule.kind != KIND_TEMPLATE and rule.entity_id
        }
        if entity_ids:
            self._unsub_states = async_track_state_change_event(
                self.hass, sorted(entity_ids), self._handle_state_event
            )

        for rule in self.rules.values():
            if not rule.enabled or rule.kind != KIND_TEMPLATE or not rule.template:
                continue
            try:
                template = Template(rule.template, self.hass)
                self._unsub_templates.append(
                    async_track_template_result(
                        self.hass,
                        [TrackTemplate(template, None)],
                        self._make_template_callback(rule.id),
                    )
                )
            except Exception:  # noqa: BLE001 - a bad template must not break setup
                _LOGGER.exception("Invalid template in rule %s", rule.id)

    @callback
    def _unsubscribe(self) -> None:
        if self._unsub_states is not None:
            self._unsub_states()
            self._unsub_states = None
        for cancel in self._unsub_templates:
            cancel()
        self._unsub_templates.clear()

    def _make_template_callback(self, rule_id: str):
        @callback
        def _handle(_event, updates) -> None:
            rule = self.rules.get(rule_id)
            if rule is None or not rule.enabled:
                return
            for update in updates:
                result = update.result
                if isinstance(result, Exception):
                    _LOGGER.warning("Template error in rule %s: %s", rule_id, result)
                    return
                self._apply(rule, as_bool(result))

        return _handle

    @callback
    def _handle_state_event(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        new_state: State | None = event.data.get("new_state")
        for rule in self.rules.values():
            if rule.enabled and rule.entity_id == entity_id and rule.kind != KIND_TEMPLATE:
                self._apply(rule, self._evaluate(rule, new_state))

    @callback
    def async_evaluate_all(self) -> None:
        """Re-evaluate every enabled rule against current state."""
        for rule in self.rules.values():
            if rule.enabled:
                self._evaluate_rule_now(rule)

    @callback
    def _evaluate_rule_now(self, rule: Rule) -> None:
        if rule.kind == KIND_TEMPLATE:
            if not rule.template:
                return
            try:
                result = Template(rule.template, self.hass).async_render(
                    parse_result=True
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Template error in rule %s", rule.id)
                return
            self._apply(rule, as_bool(result))
            return
        if not rule.entity_id:
            return
        self._apply(rule, self._evaluate(rule, self.hass.states.get(rule.entity_id)))

    @callback
    def _evaluate(self, rule: Rule, state: State | None) -> bool | None:
        """Adapt a Home Assistant State to the pure evaluator."""
        return evaluate_condition(
            rule,
            state.state if state is not None else None,
            self.manager.book.is_active(rule.alarm_key),
        )

    @callback
    def _apply(self, rule: Rule, result: bool | None) -> None:
        """Turn an evaluation result into an alarm transition."""
        if result is None:
            return

        if not result:
            self._cancel_pending(rule.id)
            self.manager.clear_alarm(rule.alarm_key)
            return

        if self.manager.book.is_active(rule.alarm_key):
            return  # already raised, nothing to do

        if rule.for_seconds > 0:
            if rule.id in self._pending:
                return

            @callback
            def _delayed(_now, rule_id: str = rule.id) -> None:
                self._pending.pop(rule_id, None)
                current = self.rules.get(rule_id)
                if current is None or not current.enabled:
                    return
                # Confirm the condition is still true before raising.
                if current.kind == KIND_TEMPLATE:
                    self._evaluate_rule_now(current)
                    return
                state = (
                    self.hass.states.get(current.entity_id)
                    if current.entity_id
                    else None
                )
                if self._evaluate(current, state):
                    self._raise(current)

            self._pending[rule.id] = async_call_later(
                self.hass, rule.for_seconds, _delayed
            )
            return

        self._raise(rule)

    @callback
    def _raise(self, rule: Rule) -> None:
        self.manager.raise_alarm(
            rule.alarm_key,
            name=rule.name,
            level=rule.level,
            entity_id=rule.entity_id,
            rule_id=rule.id,
            message=rule.message,
            notify=rule.notify,
        )

    @callback
    def _cancel_pending(self, rule_id: str) -> None:
        cancel = self._pending.pop(rule_id, None)
        if cancel is not None:
            cancel()
