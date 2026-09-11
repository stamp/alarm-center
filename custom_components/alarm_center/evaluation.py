"""Rule condition evaluation.

Extracted from ``rules.py`` and kept free of Home Assistant imports, so the
fiddliest logic in the project - hysteresis, the tri-state unknown handling,
numeric parsing - can be unit tested the same way the alarm lifecycle is.

Everything here works on a plain state string. The caller is responsible for
turning a Home Assistant ``State`` into one.
"""

from __future__ import annotations

from .const import KIND_NUMERIC, KIND_PROBLEM, KIND_STATE
from .models import Rule

STATE_ON = "on"
STATE_UNAVAILABLE = "unavailable"
STATE_UNKNOWN = "unknown"

#: State strings that mean "no usable value", as opposed to a real value.
NO_VALUE = (STATE_UNAVAILABLE, STATE_UNKNOWN)


def evaluate_condition(
    rule: Rule, state_value: str | None, currently_active: bool
) -> bool | None:
    """Decide whether a rule's condition is met.

    Returns True (condition met), False (not met), or None (can't tell -
    the caller should leave the alarm as it is rather than guess).

    ``state_value`` is the entity's state as a string, or None if the entity
    doesn't exist. ``currently_active`` is whether this rule's alarm is
    active right now, which is what makes hysteresis possible: the threshold
    to leave an alarm state differs from the one to enter it.
    """
    if state_value is None or state_value in NO_VALUE:
        # An unavailable sensor is either a problem in its own right, or
        # simply nothing we can judge - never a silent "all clear".
        return True if rule.unavailable_is_problem else None

    if rule.kind == KIND_PROBLEM:
        return state_value == STATE_ON

    if rule.kind == KIND_STATE:
        return state_value == (rule.state or STATE_ON)

    if rule.kind == KIND_NUMERIC:
        return _evaluate_numeric(rule, state_value, currently_active)

    # Template rules are evaluated by Home Assistant's template engine, not
    # here; any other kind is unknown to us.
    return None


def _evaluate_numeric(
    rule: Rule, state_value: str, currently_active: bool
) -> bool | None:
    """Threshold comparison with hysteresis."""
    try:
        value = float(state_value)
    except (TypeError, ValueError):
        return None

    if rule.above is None and rule.below is None:
        return None

    hysteresis = abs(rule.hysteresis or 0.0)

    if rule.above is not None:
        if value > rule.above:
            return True
        # Already alarming: stay alarming until the value has come back
        # down past the threshold by the full hysteresis band.
        if currently_active and value > rule.above - hysteresis:
            return True

    if rule.below is not None:
        if value < rule.below:
            return True
        if currently_active and value < rule.below + hysteresis:
            return True

    return False


def as_bool(value: object) -> bool | None:
    """Interpret a template result as a boolean.

    Templates can return real booleans, numbers, or strings depending on how
    they're written, and an unrenderable one should read as "can't tell"
    rather than False.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "on", "yes", "1"):
        return True
    if text in ("false", "off", "no", "0", ""):
        return False
    if text in (STATE_UNKNOWN, STATE_UNAVAILABLE, "none"):
        return None
    return None
