# Contributing

Contributions are welcome - bug reports, fixes, and features from
[the roadmap](docs/ROADMAP.md) alike.

## Getting set up

There is no build step and no dependencies beyond Home Assistant itself. To
work on the code:

```bash
git clone https://github.com/stamp/alarm-center
cd alarm-center
python3 -m unittest discover -s tests -v
node --check custom_components/alarm_center/frontend/panel.js
node --check custom_components/alarm_center/frontend/alarm-center-card.js
```

The tests deliberately run without Home Assistant installed - see below.

To try a change in a real Home Assistant, symlink or copy
`custom_components/alarm_center` into your `config/custom_components/` and
restart. Frontend changes only need a hard reload (Ctrl+Shift+R), since the
static files are served without cache headers - but bump `VERSION` in
`const.py` when you release, because the panel URL's cache-busting query
string comes from it.

## Testing

`tests/` runs on plain `unittest` with no Home Assistant and no pytest,
which is possible because the logic worth testing has been kept free of
Home Assistant imports:

| Module | What it holds |
|---|---|
| `lifecycle.py` | The alarm state machine |
| `models.py` | `Alarm` and `Rule` |
| `evaluation.py` | Thresholds, hysteresis, tri-state unknowns |
| `schedule.py` | Quiet-hours time windows |

**Please keep it that way.** If you find yourself wanting to test something
that needs `hass`, that is usually a sign the decision logic should be
extracted into one of these modules and the Home Assistant module reduced to
an adapter. `rules.py` calling `evaluate_condition()` is the pattern to
follow.

Anything that genuinely needs Home Assistant - entity platforms, the
websocket API, notification fan-out - is currently verified by hand against
a live installation. If you want to add a
`pytest-homeassistant-custom-component` suite for those, that would be a
very welcome contribution.

## Conventions

* **Python**: standard Home Assistant style. Async throughout, `@callback`
  for synchronous handlers, type hints, docstrings on public methods.
* **Frontend**: no build step, and please keep it that way. Plain custom
  elements, native form controls, Home Assistant's own CSS variables for all
  colours so themes work. Home Assistant lazy-loads most of its form
  elements, so `ha-textfield` and friends cannot be relied on being defined
  - that is why the panel uses native inputs.
* **Comments** explain *why*, not *what*. The non-obvious decisions -
  administrative clears not running user actions, an empty quiet-hours
  window meaning empty rather than always - carry a comment saying so.
* **User-facing text is English**, so the component is usable by anyone.
  Translations belong in `custom_components/alarm_center/translations/`.

## Pull requests

* One logical change per PR.
* Add or update tests when you touch any of the four pure modules.
* Update the README when you change behaviour a user would notice, and
  [docs/ROADMAP.md](docs/ROADMAP.md) when you close a gap listed there.
* Say what you verified against a real Home Assistant and what you did not.
  Being explicit about the untested parts is more useful than implying
  everything was checked.

## Using an AI assistant

Plenty of this project was written with one. If you do the same, load
[AGENTS.md](AGENTS.md) first - it carries the architectural decisions and
the pitfalls that are expensive to rediscover. Please still review what it
produces and test it against a real installation before opening a PR; the
Home Assistant API surface is exactly where a confident-sounding assistant
tends to be wrong.
