# Roadmap and known gaps

An honest account of what Alarm Center does not do yet, and what is worth
doing next. Contributions in any of these areas are welcome - see
[CONTRIBUTING.md](../CONTRIBUTING.md).


Roughly in the order they'd pay off.

### Missing alarm-handling features

* **No dependency suppression.** If the network goes down and forty problem
  sensors go unavailable, you get forty alarms. Letting a rule declare a
  parent ("don't alarm if `binary_sensor.wan_down` is on") would collapse
  those into one. This is now the biggest functional gap.
* **No escalation to a different person.** Repeats re-notify the same
  people forever. Escalating to someone else after N unanswered reminders
  would need a per-target "escalation order" and a count of reminders sent,
  both of which the scheduler is already close to having.
* **Quiet hours are global, not per person.** Someone on call and someone
  who just doesn't want to be woken have different needs, but they share one
  window. The per-person `min_level` already exists, so a per-person
  override would fit naturally alongside it.
* **Only `for_seconds`, no `delay_off`.** A flapping sensor is handled on
  the way up but not on the way down. `archive_delay` partly compensates,
  but they're different mechanisms for different problems.
* **Reminder and deferral state is in memory.** A restart resets repeat
  clocks and discards anything quiet hours was holding. Persisting both in
  `.storage` alongside the open alarms would be straightforward.

### Design decisions worth revisiting

* **Re-notification of acknowledged alarms.** As it stands, an alarm that's
  been acknowledged but goes inactive and active again notifies again, since
  notifications key off "became active". That's defensible - it is a new
  activation - but it may be unwanted for known-flappy sensors. There's a
  test (`test_became_active_survives_acknowledgement`) documenting the
  current behaviour so it changes deliberately rather than by accident.
* **`acknowledged_by_name` is a snapshot.** The user's display name at
  acknowledgement time is copied into history. If a user is renamed, old
  entries keep the old name. Arguably correct for an audit log, but worth a
  conscious decision.
* **Trash is capped at 50 and never expires.** Fine in practice, but there's
  no age-based pruning, so a one-off bulk delete could push out entries you
  wanted.
* **No shelving, deliberately.** Acknowledging already means "seen and
  parked", which covers what shelving is for in an industrial system.

### Robustness and code quality

* **History is read by loading whole files.** `_read_history` calls
  `readlines()` on a month's file to serve a paged request. Fine at
  household scale, wasteful at thousands of alarms per month, and there's no
  pruning of old files at all.
* **No `_data(hass)` guard in most websocket handlers.** Only
  `ws_subscribe` handles the "integration not loaded" case; the rest would
  raise. Only reachable in a narrow window during reload, but it's a
  one-line fix per handler.
* **Every state change walks every rule.** `_handle_state_event` loops all
  rules to find matching ones. Irrelevant at tens of rules, worth an
  entity_id → rules index at hundreds.
* **The notifier itself is untested.** The pure pieces it depends on
  (`evaluation.py`, `schedule.py`, `lifecycle.py`) all have coverage now,
  but the fan-out logic - which target gets what, at which level, with which
  payload - only runs against a live Home Assistant. It's the most complex
  remaining code without tests.
* **Actions are edited as JSON, not YAML.** There's no YAML parser in the
  frontend and Home Assistant's own action editor isn't usable from a custom
  panel, so the rule editor asks for JSON. Works, but it's the roughest edge
  in the UI.

### Untested against a live system

Everything here has been syntax-checked and the lifecycle is unit tested,
but the Home Assistant API surface has never run against a real instance.
The things most likely to need adjusting on first load, in rough order of
risk: `panel_custom.async_register_panel` and `StaticPathConfig`
signatures (both have changed across HA versions), whether
`ha-entity-picker` actually loads via the `loadCardHelpers` trick,
`NotifyEntity` entity_id composition, and the mobile app payload fields
(`channel`, `importance`, `media_stream`).
