# Architecture

Internals of Alarm Center. For installation and day-to-day use, see the
[README](../README.md).

## How the code is laid out

| File | Responsibility |
|---|---|
| `lifecycle.py` | The alarm state machine. Pure Python, no HA imports, fully unit tested. |
| `models.py` | `Alarm` and `Rule` dataclasses plus serialisation. Also HA-free. |
| `evaluation.py` | Rule condition evaluation - thresholds, hysteresis, tri-state unknowns. HA-free and unit tested. |
| `schedule.py` | Time-window maths for quiet hours, including midnight wrap. HA-free and unit tested. |
| `manager.py` | Wraps the state machine with side effects: timers, actions, notifications, persistence, dispatch. |
| `rules.py` | Rule storage and CRUD, state subscriptions, auto-rule sync, trash. |
| `notifier.py` | Who to notify and how - person resolution, channels, TTS, quiet hours. |
| `reminders.py` | The digest, repeat-reminder and quiet-hours-end timers. |
| `notify_target.py` | Alarm Center as a classic `notify.*` service target. |
| `notify.py` | The same, as entity-platform notify entities. |
| `websocket_api.py` | Everything the panel talks to. |
| `store.py` | `.storage` config/state plus rotating JSONL history. |
| `sensor.py` / `binary_sensor.py` | Counter and flag entities for dashboards and automations. |
| `frontend/panel.js` | The sidebar panel. No build step. |
| `frontend/alarm-center-card.js` | The dashboard card. No build step. |

The split that matters: `lifecycle.py`, `models.py`, `evaluation.py` and
`schedule.py` contain the rules that are easy to get subtly wrong and hard
to debug in a live system, and they're testable without Home Assistant.
Everything that needs a running Home Assistant sits above them.


## The alarm model

| Field | Meaning |
|---|---|
| `key` | Stable identity of the condition (`rule:<id>` or `manual:<key>`) |
| `id` | Identity of this particular alarm occurrence |
| `active` | Whether the condition is true right now |
| `acknowledged` | Whether someone or an auto-ack rule has acknowledged it |
| `level` | `critical`, `error`, `warning`, `notice` |
| `activated_at` / `last_activated_at` | First and most recent activation |
| `deactivated_at` | When the alarm last stopped being active |
| `acknowledged_at` / `acknowledged_by` / `acknowledged_by_name` | Who and when |
| `activation_count` | Number of activations without an acknowledgement |

The lifecycle lives in `lifecycle.py` and is free of Home Assistant
dependencies, so it's tested with plain `unittest`:

```bash
python3 -m unittest discover -s tests -v
node --check custom_components/alarm_center/frontend/panel.js
```

Rules the tests cover:

* An alarm stays in the list until it is **both** acknowledged and inactive.
* If an unacknowledged alarm goes inactive and active again, it's the same
  alarm - only `last_activated_at` and `activation_count` change.
* After archiving, the next activation produces a new alarm.

### archive_delay

Once an alarm becomes both acknowledged and inactive, a timer starts
(`archive_delay`, set globally in settings or per rule). If the alarm
becomes active again within that time, the move to history is cancelled, so
a flapping sensor doesn't generate a string of alarms. Set to `0` to archive
immediately.

### auto_acknowledge

A rule with `auto_acknowledge` acknowledges its alarm when the condition
becomes false. The rule still uses the ordinary clear and acknowledge paths:
`on_clear` runs, the active notification is removed, `on_acknowledge` runs,
and `archive_delay` controls when the acknowledged inactive alarm is written
to history. A quick reactivation before automatic acknowledgement is ignored
by the automatic step, so the active alarm remains unacknowledged.

