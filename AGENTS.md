# AGENTS.md

Context for AI assistants working on Alarm Center. Read this before
changing anything; it carries the decisions and pitfalls that are expensive
to rediscover.

## What this is

A Home Assistant custom integration providing an alarm center / event log
with its own sidebar panel. Domain `alarm_center`. No build step, no runtime
dependencies beyond Home Assistant.

* User-facing docs: [README.md](README.md)
* Internals: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Known gaps: [docs/ROADMAP.md](docs/ROADMAP.md)
* Contributor conventions: [CONTRIBUTING.md](CONTRIBUTING.md)

## Commands

```bash
python3 -m unittest discover -s tests -v          # 42 tests, no HA needed
node --check custom_components/alarm_center/frontend/panel.js
node --check custom_components/alarm_center/frontend/alarm-center-card.js
python3 -m compileall -q custom_components/alarm_center
```

There is no linter configured and no pytest. Tests import the modules
through a stub package so the Home Assistant-importing `__init__.py` never
runs - see the top of any test file.

## The core invariants

Break these and the component is wrong in ways users will not report
clearly. They are enforced by tests in `tests/test_lifecycle.py`.

1. **An alarm leaves the open list only when acknowledged AND inactive.**
   Never one or the other.
2. **A flapping unacknowledged alarm is one alarm, not many.** Identity is
   `key` (stable, per condition); `id` is the occurrence. Reactivation keeps
   both, bumps `activation_count` and `last_activated_at`, and preserves the
   original `activated_at`.
3. **Acknowledgement records who and when**, from every route: panel, card,
   notification action button, service call.
4. **`became_active` is the trigger for outbound noise**, not `created`.
   Notifications and `on_activate` actions fire whenever the alarm becomes
   active, including a reactivation - but never for a repeated raise while
   already active.
5. **Administrative clears must not run user actions.** Disabling or
   deleting a rule calls `clear_alarm(..., run_actions=False)`, because the
   fault did not go away - only the monitoring did. This was a real bug
   once; do not regress it.

## Architecture rule: keep logic out of Home Assistant modules

Four modules are free of Home Assistant imports and unit tested:
`lifecycle.py`, `models.py`, `evaluation.py`, `schedule.py`. Everything that
needs `hass` sits above them as an adapter.

When adding decision logic, put it in one of those four (or a new HA-free
module) and have the Home Assistant side call into it. `rules.py._evaluate`
is three lines that adapt a `State` into `evaluate_condition()` - that is
the pattern. Do not inline new conditional logic into `rules.py`,
`manager.py` or `notifier.py` if it can be expressed purely.

## Non-obvious decisions

* **`ha-textfield` and other Home Assistant form elements cannot be relied
  on.** The frontend lazy-loads them, and an undefined custom element has no
  `.value`, which silently yields `undefined`. The panel uses native
  `<input>`/`<select>`/`<textarea>` styled with theme CSS variables for this
  reason. `ha-entity-picker` is used *only* when
  `customElements.get(...)` confirms it exists, with a `<datalist>`
  fallback. Do not "improve" this by switching to Home Assistant components.
* **The panel re-renders by replacing `innerHTML`.** Therefore the click
  handler must return early when the click was not on an action element, or
  typing in a form gets wiped. Errors are shown in a banner outside the
  re-rendered region for the same reason.
* **Storage lives in `.storage/` and `<config>/`** so Home Assistant's
  backup covers it - that was an explicit requirement. History is JSONL
  files rather than `Store`, because `Store` loads everything into memory.
* **Quiet hours with equal start and end mean an empty window**, not the
  whole day - a typo should not silence everything forever.
* **The integration's own `binary_sensor` entities use device class
  `problem`** and are excluded from auto-rule generation by checking the
  entity registry platform. Without that, it alarms on itself.
* **Both notify flavours exist on purpose.** `notify_target.py` (classic
  services) and `notify.py` (entity platform) both delegate to
  `NotifyTargets.async_handle_*`. The entity platform cannot carry a `data`
  dict, which is why the services remain the fuller interface.

## Verified vs not

Be honest about this in any summary you write; it is the most useful thing
you can tell a human reviewer.

**Verified:** the 42 unit tests, JavaScript syntax, Python compilation.

**Not verified by automated means:** every Home Assistant API call. The
highest-risk surfaces, in rough order: `panel_custom.async_register_panel`
and `StaticPathConfig` signatures (both changed across HA versions),
`frontend.add_extra_js_url`, `NotifyEntity` entity_id composition, whether
`ha-entity-picker` loads via the `loadCardHelpers` trick, and the mobile app
payload fields (`channel`, `importance`, `media_stream`, `tts_text`).

Do not claim something works in Home Assistant because it compiles.

## Brand assets

`custom_components/alarm_center/brand/` holds `icon.png`, `icon@2x.png`,
`logo.png` and `logo@2x.png`. HACS requires at least `icon.png` there, or
the domain must be registered in home-assistant/brands. They are generated
by `scripts/make_brand.py` (Pillow, drawn at 4x and downsampled) - edit the
script rather than the PNGs.

## Versioning

`manifest.json` is the single source of truth. There is deliberately no
`VERSION` constant any more - `__init__.py` reads the version from the
loaded integration via `async_get_integration()` and uses it to bust the
browser cache for `panel.js` and the card. Keeping two copies in sync by
hand failed in practice, twice.

Releasing: create a GitHub release with tag `vX.Y.Z`. The release workflow
stamps that version into `manifest.json` inside the published
`alarm_center.zip` asset, which is what HACS installs (`zip_release` is set
in `hacs.json`), then commits the same update to the repository's default
branch. The tag points to the pre-stamp commit by design.
