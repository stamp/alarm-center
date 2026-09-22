# Alarm Center for Home Assistant

[![hacs][hacs-shield]][hacs-url]
[![release][release-shield]][release-url]
[![license][license-shield]](LICENSE)

An alarm center and event log for Home Assistant, with its own panel in the
sidebar.

Home Assistant is good at telling you something happened. It is less good at
tracking that somebody *noticed*. Alarm Center adds the piece industrial
alarm systems have always had: an alarm stays on the list until it is both
resolved **and** acknowledged by a named person, with a timestamped record
of who acknowledged it and when.

## What it does

* **A real alarm lifecycle** - `active` and `acknowledged` are independent,
  an alarm stays listed until both are satisfied, and acknowledgements are
  attributed to the logged-in user.
* **Its own sidebar panel** - alarms, history, rules and settings, on
  desktop and in the mobile app, themed from Home Assistant's own variables.
* **A condensed dashboard card** for an overview page.
* **Rules as the single alarm source** - problem entities, numeric
  thresholds with hysteresis, state matches and Jinja templates.
* **Automatic rules** for every `binary_sensor` with device class `problem`,
  kept in sync as entities come and go, each individually toggleable so it
  is visible what is actually monitored.
* **A trash** for deleted rules, so a mistaken delete is recoverable.
* **Per-rule actions** on activate, acknowledge and clear - full Home
  Assistant action syntax, so acknowledging can restart the faulty device.
* **Auto-acknowledge** for rules that should move to history automatically
  when their condition clears.
* **Notifications to people, not devices**, with per-level Android channels,
  actionable acknowledge buttons, auto-clearing and optional TTS over the
  alarm stream.
* **Reminders that nag** - a daily "still active" digest plus per-level
  repeats for unacknowledged alarms, replacing the previous notification
  rather than piling up.
* **Quiet hours** that hold chosen levels back and release them afterwards.
* **A notify target of its own**, so automations can raise an
  acknowledgeable alarm or reach a person by name.
* **Everything in `config`**, so Home Assistant's built-in backup covers it.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and show the HACS repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=stamp&repository=alarm-center&category=integration)

Alarm Center is not in the default HACS list, so add it as a custom
repository:

1. In Home Assistant, go to **HACS → Integrations**.
2. Open the three-dot menu in the top right and choose
   **Custom repositories**.
3. Paste the URL of this repository, choose category **Integration**, and
   select **Add**.
4. Find **Alarm Center** in the list, select **Download**, and restart Home
   Assistant.

### Manual

Copy the `custom_components/alarm_center` directory into your Home
Assistant `config/custom_components/` directory, so you end up with
`config/custom_components/alarm_center/manifest.json`, then restart Home
Assistant.

### Set up the integration

After restarting, go to **Settings → Devices & services → Add integration**
and search for **Alarm Center**. There is nothing to fill in - everything is
configured from the panel afterwards. **Alarm Center** then appears in the
sidebar.

Requires Home Assistant 2025.1 or newer.

## Getting started

**1. See what is already monitored.** Open the panel and go to **Rules**. A
rule has been created automatically for every `binary_sensor` with device
class `problem` that Home Assistant knows about - low battery sensors,
printer errors, appliance faults. Each has a switch. Turn off the ones you
do not care about; they stay in the list so it is always visible what is and
is not watched.

**2. Add a rule of your own.** Select **New rule**. To alarm on a battery
running low, choose type **Numeric value**, pick the sensor, set *Alarm
below* to `20`, and set *Hysteresis* to `5` so a sensor wobbling around 20%
does not produce a stream of alarms. Level **Warning** is a reasonable
default; **Critical** is for things that should wake someone.

**3. Decide who hears about it.** Go to **Settings → Notifications**, tick
the people who should be notified, and set the lowest level each of them
cares about. The notify services for their phones are detected
automatically from their `person` entity; you can override them by hand.

**4. Try it.** Trigger the condition. The alarm appears in the panel, a
notification arrives with an **Acknowledge** button, and acknowledging it -
from the panel, the card or the notification - records your name against it.
Once the condition clears as well, the alarm moves to **History**.

**5. Put it on a dashboard.** Add a card with type
`custom:alarm-center-card` to any dashboard for a condensed list, with
acknowledge buttons, next to your other cards.

## Concepts

An alarm has two independent flags, and understanding them is most of
understanding Alarm Center:

* **active** - the condition is true right now. Set and cleared by the rule.
* **acknowledged** - a person or an auto-acknowledge rule has taken ownership
  of it.

An alarm leaves the list only when **both** are satisfied: resolved and
acknowledged. An unacknowledged alarm that flaps off and on again is the
same alarm, not a new one - only its activation count and latest activation
time change. Acknowledging is also what stops reminders: it means someone
has taken ownership, whether or not the fault is fixed yet.

Levels, most severe first: `critical`, `error`, `warning`, `notice`.

## Rules

Every alarm source is a rule, including the auto-generated ones. Kinds:

* `problem` - a `binary_sensor` with device class `problem` is `on`
* `numeric` - above/below a threshold, with hysteresis
* `state` - the entity is in a given state
* `template` - a Jinja expression that evaluates to true/false

Other fields: `for_seconds` (delay before the alarm fires), `archive_delay`,
`unavailable_is_problem`, `notify`, `notify_targets`, `auto_acknowledge`,
`message`.

### Automatic rules for problem entities

At startup, whenever the entity registry changes, and every ten minutes,
every `binary_sensor` with device class `problem` is scanned. If an entity
has no rule yet, one is created at the configured default level. The rule
shows up in the rule list and can be turned off - that stops monitoring the
entity without deleting the rule. Deleting an auto rule adds the entity to
`auto_rules.ignored` so it isn't immediately recreated (see Trash below for
how to undo a deletion instead).

The integration's own `binary_sensor` entities are skipped, or Alarm Center
would end up alarming on itself.

### Deleted rules go to the trash

Deleting a rule doesn't discard it - it moves into a trash list (capped at
the 50 most recent, oldest dropped first) and can be restored from the
panel's **Rules → Trash** view at any time, with its settings and actions
intact. This matters most for auto-generated rules: deleting one by mistake
no longer means re-entering its settings from scratch, and restoring it also
removes it from `auto_rules.ignored` so it goes back to being monitored.
Trash entries can also be purged permanently from the same view.

### Actions on activate, acknowledge, and clear

Every rule can have `on_activate`, `on_acknowledge` and `on_clear` -
sequences in Home Assistant's normal action syntax, run through `Script`.
Useful for restarting a device when the acknowledge button is pressed:

```json
[
  {"action": "switch.turn_off", "target": {"entity_id": "switch.pump"}},
  {"delay": {"seconds": 5}},
  {"action": "switch.turn_on", "target": {"entity_id": "switch.pump"}}
]
```

The variables `alarm` and `rule` are available in templates inside the
sequence. An error in an action is logged but never blocks the
acknowledgement itself.

When each one runs:

* `on_activate` fires every time the alarm **becomes** active - on first
  activation and on a reactivation after having gone inactive, but not for
  repeated raises while it's already active. Same trigger as notifications.
* `on_clear` fires when the condition genuinely stops being true. It does
  **not** fire when a rule is disabled or deleted, because the fault didn't
  go away in that case - only the monitoring did.
* `on_acknowledge` fires when someone acknowledges, from any route: panel,
  card, notification button, or the `alarm_center.acknowledge` service. It
  also fires for automatic acknowledgement.

Enable `auto_acknowledge` on a rule when a resolved condition should not wait
for a person. When the condition becomes false, the normal clear flow runs
first, including `on_clear` and notification removal, then the normal
acknowledge flow runs. The acknowledgement is attributed to
`Auto-acknowledge`, and the configured `archive_delay` still controls the
grace period before the alarm is written to history.

## Notifications

A notification target is a person plus the notify services that reach that
person's devices. Services are auto-detected from the person's device
trackers (`mobile_app`) and can be overridden by hand in the panel. Each
target has a minimum level.

The notification mirrors whether the condition is active right now, not the
alarm's acknowledgement status:

* It's sent (or re-sent) every time an alarm becomes active - on first
  activation and on reactivation after having gone quiet. It is *not* sent
  for calling the same alarm again while it's already active.
* It's removed automatically once the fault goes inactive (`clear_alarm`) -
  the alarm stays in the list, dimmed, until it's acknowledged, but a phone
  notification for a condition that no longer holds is just noise.
* It's also removed on acknowledgement, regardless of whether the condition
  is still active - acknowledging means the alarm has been seen.

Every notification gets `tag` = the alarm's id, so the app replaces rather
than stacks them, plus an actionable "Acknowledge" button that acknowledges
directly from the notification via `mobile_app_notification_action`.

### Reminders and repeats

An alarm that notifies once and then goes quiet is easy to forget about, so
there are two independent nagging mechanisms, both configured in the panel.

**Daily digest.** At a set time of day, one notification listing every alarm
that is still active, at or above a chosen level, with a count of how many
are unacknowledged. Nothing is sent when there's nothing active. It uses its
own fixed tag, so each morning's summary replaces the previous one instead
of stacking.

**Per-level repeat.** Each level gets its own interval in minutes, `0` being
off - the obvious setup is hourly for critical and off for everything else.
An alarm is only repeated while it is **both active and unacknowledged**:
acknowledging is what stops the nagging, since it means someone has seen it
and taken ownership whether or not it's fixed yet. The previous notification
is cleared before the new one is sent and the tag is reused, so the phone
shows one current notification per alarm rather than an accumulating pile.

A single timer ticks once a minute and checks intervals itself, rather than
one timer per alarm. Reminder timestamps are kept in memory, so a Home
Assistant restart resets the clock for pending alarms - the first reminder
after a restart comes one full interval later.

### Quiet hours

A time window during which chosen levels are held back rather than sent.
Levels left unticked always get through immediately, so critical can stay
loud all night while notice waits until morning.

The window is allowed to wrap past midnight - 22:00 to 07:00 means the
night, which is the only way anyone actually wants to configure this. Start
is inclusive, end is exclusive, and a window whose ends are equal is treated
as empty rather than as the whole day, so a typo can't silence everything
forever. That logic lives in `schedule.py` and has its own tests.

When the window ends, everything held back is sent - except alarms that
resolved or were acknowledged in the meantime, which are dropped rather than
delivered late. Waking someone at 07:00 for a fault that cleared at 01:00 is
exactly the noise quiet hours exist to prevent. The held-back list is kept in
memory, so a restart during quiet hours loses it.

### Per-level channels (Android)

Each level is sent with its own `channel` name (`Alarm Center - Critical`,
`- Error`, `- Warning`, `- Notice`) and `importance` (high for
critical/error, normal for warning, low for notice). Android creates the
channels automatically on the first notification at each level, and they can
be muted individually in the phone's own notification settings for the Home
Assistant app - without affecting the other levels.

A channel's priority is set by Android the first time it's created. Changing
`importance` in the code later doesn't take effect for users who already
have the channel - they'd need to clear the app's notification data, or
uninstall and reinstall, to pick up the new priority.

### Text-to-speech (TTS) via the alarm stream

Can be turned on in the panel's settings, globally plus one audio stream per
level: off, `alarm_stream`, or `alarm_stream_max`. `alarm_stream_max` plays
through Android's alarm stream and is heard even if the phone is muted or in
Do Not Disturb (requires the Home Assistant app to have that permission on
the phone). Each person has their own "Read aloud" checkbox - only those who
enabled it get the TTS call, in addition to the normal notification.

TTS is sent as a separate `notify` call with `message: "TTS"` and
`data: {media_stream, tts_text}`, following the same "became active"
principle as notifications above. It doesn't repeat just because the alarm
is still active, only when it becomes active.

## Alarm Center as a notification target

Home Assistant now has two ways for an integration to be a notify target,
and Alarm Center supports both in parallel so it works regardless of what
automations and scripts expect:

* **Classic services** (`notify_target.py`) - the same mechanism every older
  notify platform has used, registered directly under the `notify` domain.
* **The newer entity-based notify platform** (`notify.py`) - shows up as its
  own `notify.*` entities and appears in target pickers in the UI.

Both routes end up in the same logic in `notify_target.py`
(`NotifyTargets.async_handle_global` / `.async_handle_person`), so they
behave identically for the common case. The difference: the entity
platform's `async_send_message` only carries a message and a title - no
free-form `data` field - so the extra functionality (level, key, `clear`,
scoping an alarm to one person) is only available through the services
below.

### `notify.alarm_center` - global, raises an alarm

Sending a notification here raises an alarm in the alarm list that can be
acknowledged right away, just like any other alarm - including channel,
TTS, and notifications to configured recipients through the same pipeline
as rule-based alarms.

```yaml
service: notify.alarm_center
data:
  title: "Boiler room leak"
  message: "The floor drain sensor triggered"
  data:
    level: critical    # critical | error | warning | notice, default warning
    key: boiler_room_leak  # optional, otherwise derived from the title
    clear: false        # set to true to deactivate the alarm again
    notify: true         # whether to send notifications for this alarm
```

The same thing can be done by sending a message to the entity
`notify.alarm_center` (the entity-based variant, which ends up with a
matching entity_id) - but always at the default level `warning`, since the
entity platform has no room for the `data` field.

`key` shares a namespace with the `alarm_center.raise_alarm` /
`.clear_alarm` services (both use `manual:<key>`) - the same key
reactivates the same alarm regardless of which route created it.

### `notify.alarm_center_<person>` - one service per person

A service is registered automatically for every `person.*` entity (e.g.
`notify.alarm_center_stamp` for `person.stamp`), refreshed at startup, on
person registry changes, and every ten minutes. Sending a notification here
forwards it to that person's discovered `notify.mobile_app_*` services - so
an automation can address a specific person instead of a specific phone:

```yaml
service: notify.alarm_center_stamp
data:
  title: "Reminder"
  message: "Don't forget to close the gate"
```

The same forwarding exists as a notify entity too (one per person, named
after the device so entity_id and service name match), for sending from the
UI's target picker or from integrations that only support entity-based
notify targets.

Add `data.alarm: true` to instead raise it as an alarm scoped to just that
person (gets its own acknowledgeable alarm in the list, but notifications go
only to that person's devices, regardless of what's configured in settings):

```yaml
service: notify.alarm_center_stamp
data:
  title: "Freezer"
  message: "Temperature is rising"
  data:
    alarm: true
    level: error
```

(This needs the service route, not the entity, since `alarm`/`level` live in
`data`.)

If a person has no discovered `mobile_app` target, a warning is logged
instead of the call failing silently.

One limitation worth knowing: Home Assistant only renders a service's
YAML/UI form from a `services.yaml` in *that* service's own domain. Since
these services are registered under `notify`, not `alarm_center`, they get
no such form - they work perfectly but need to be filled in as YAML in the
automation editor.

## Storage and backup

* `.storage/alarm_center.config` - rules, trash, and settings (including
  reminder and quiet-hours configuration)
* `.storage/alarm_center.state` - open alarms (survives a restart)
* `<config>/alarm_center/history-YYYY-MM.jsonl` - archived alarms

Everything lives under the `config` directory and is included in Home
Assistant's built-in backup. History is kept in files rather than in
`Store` because `Store` reads the whole file into memory.

## Entities, services, and events

Sensors: `sensor.alarm_center_open_alarms`, `..._active_alarms`,
`..._unacknowledged_alarms`, `..._highest_alarm_level`, plus
`binary_sensor.alarm_center_alarm_active` and `..._unacknowledged_alarm`.
(Exact entity ids depend on how Home Assistant slugifies the names on your
system.)

Services: `alarm_center.raise_alarm`, `.clear_alarm`, `.acknowledge`,
`.acknowledge_all`.

Every transition fires `alarm_center_event` on the bus with `action` =
`raised` / `reactivated` / `cleared` / `acknowledged` / `archived`.

## The panel

`frontend/panel.js` is a plain custom element with no build step. It uses
Home Assistant's own elements (`ha-card`, `ha-icon`, `ha-icon-button`) and
the theme's CSS variables, so light/dark theming follows along. The menu
button sends `hass-toggle-menu` so the sidebar can be opened from the app.
Acknowledged alarms are shown dimmed and without the level color highlight.

Updates are pushed over websocket (`alarm_center/subscribe`), no polling.
Write commands require admin.

## Dashboard card

`alarm-center-card.js` is a plain lovelace card showing a condensed alarm
list - one row per alarm, level icon, name, acknowledge button. Meant to sit
on an overview dashboard alongside other cards, not as a replacement for the
panel. Needs no manual resource; the integration registers it on every page
via `frontend.add_extra_js_url`.

Add it to a dashboard as a normal YAML card:

```yaml
type: custom:alarm-center-card
title: Alarms
max_items: 5
show_acknowledged: true
show_ack_button: true
tap_action: more-info   # more-info | panel | none
levels: [critical, error]  # optional, otherwise all levels
```

Clicking a row opens the entity's more-info dialog (or the panel, with
`tap_action: panel`); clicking Ack acknowledges directly without leaving the
dashboard. The card shares the same websocket subscription as the panel, so
both update at the same time.

## Branding

Brand assets live in `custom_components/alarm_center/brand/` - `icon.png`
(256x256), `icon@2x.png` (512x512), `logo.png` and `logo@2x.png`. HACS looks
for a local brand directory first and only falls back to the
[home-assistant/brands](https://github.com/home-assistant/brands) repository
if there isn't one.

They're generated rather than drawn, so they can be changed reproducibly:

```bash
python3 scripts/make_brand.py
```

## Documentation

* [Architecture](docs/ARCHITECTURE.md) - how the code is laid out, the alarm
  model in detail, and why the pure/impure split is where it is.
* [Roadmap and known gaps](docs/ROADMAP.md) - an honest account of what this
  does not do yet.
* [Contributing](CONTRIBUTING.md) - development setup, tests, conventions.

## Credits

Built by [Stamp](https://github.com/stamp) together with Claude
(Anthropic), as a genuine collaboration rather than either generating it
alone: the requirements, the alarm semantics, the design decisions and the
testing against a real Home Assistant installation are Stamp's; much of the
implementation and documentation was written by Claude in dialogue with
him.

If you work on this with an AI assistant, [AGENTS.md](AGENTS.md) contains
the project context worth loading first.

## License

MIT - see [LICENSE](LICENSE).

[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://hacs.xyz
[release-shield]: https://img.shields.io/github/v/release/stamp/alarm-center
[release-url]: https://github.com/stamp/alarm-center/releases
[license-shield]: https://img.shields.io/github/license/stamp/alarm-center
