"""Tests for rule condition evaluation.

Run without Home Assistant installed:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path

# Load the modules directly, without running the package __init__ (which
# imports Home Assistant). Relative imports still resolve inside this stub.
_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "alarm_center"
if "_alarm_center" not in sys.modules:
    _pkg = types.ModuleType("_alarm_center")
    _pkg.__path__ = [str(_COMPONENT)]
    sys.modules["_alarm_center"] = _pkg

_evaluation = importlib.import_module("_alarm_center.evaluation")
evaluate_condition = _evaluation.evaluate_condition
as_bool = _evaluation.as_bool
Rule = importlib.import_module("_alarm_center.models").Rule


def rule(**kwargs) -> Rule:
    """A rule with sensible defaults for whatever isn't under test."""
    kwargs.setdefault("id", "r1")
    kwargs.setdefault("name", "Test")
    return Rule(**kwargs)


class ProblemRuleTest(unittest.TestCase):
    """device_class problem binary sensors."""

    def test_on_is_a_problem(self) -> None:
        r = rule(kind="problem", entity_id="binary_sensor.x")
        self.assertTrue(evaluate_condition(r, "on", False))

    def test_off_is_not(self) -> None:
        r = rule(kind="problem", entity_id="binary_sensor.x")
        self.assertFalse(evaluate_condition(r, "off", True))


class StateRuleTest(unittest.TestCase):
    """Matching an arbitrary state string."""

    def test_matches_configured_state(self) -> None:
        r = rule(kind="state", entity_id="vacuum.x", state="error")
        self.assertTrue(evaluate_condition(r, "error", False))
        self.assertFalse(evaluate_condition(r, "docked", False))

    def test_defaults_to_on(self) -> None:
        r = rule(kind="state", entity_id="switch.x")
        self.assertTrue(evaluate_condition(r, "on", False))


class UnavailableTest(unittest.TestCase):
    """Unavailable must never read as an all-clear."""

    def test_unknown_by_default(self) -> None:
        r = rule(kind="problem", entity_id="binary_sensor.x")
        self.assertIsNone(evaluate_condition(r, "unavailable", False))
        self.assertIsNone(evaluate_condition(r, "unknown", False))
        self.assertIsNone(evaluate_condition(r, None, False))

    def test_can_be_treated_as_a_problem(self) -> None:
        r = rule(
            kind="problem", entity_id="binary_sensor.x", unavailable_is_problem=True
        )
        self.assertTrue(evaluate_condition(r, "unavailable", False))
        self.assertTrue(evaluate_condition(r, None, False))

    def test_active_alarm_is_not_cleared_by_unavailable(self) -> None:
        """None means "leave it alone" - an active alarm stays active."""
        r = rule(kind="numeric", entity_id="sensor.x", below=20)
        self.assertIsNone(evaluate_condition(r, "unavailable", True))


class NumericTest(unittest.TestCase):
    """Thresholds without hysteresis."""

    def test_below(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.battery", below=20)
        self.assertTrue(evaluate_condition(r, "19", False))
        self.assertFalse(evaluate_condition(r, "20", False))
        self.assertFalse(evaluate_condition(r, "21", False))

    def test_above(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.temp", above=80)
        self.assertTrue(evaluate_condition(r, "81", False))
        self.assertFalse(evaluate_condition(r, "80", False))

    def test_both_thresholds_form_a_band(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.x", above=30, below=10)
        self.assertTrue(evaluate_condition(r, "35", False))
        self.assertTrue(evaluate_condition(r, "5", False))
        self.assertFalse(evaluate_condition(r, "20", False))

    def test_no_threshold_is_unknown(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.x")
        self.assertIsNone(evaluate_condition(r, "5", False))

    def test_non_numeric_state_is_unknown(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.x", below=20)
        self.assertIsNone(evaluate_condition(r, "not a number", False))


class HysteresisTest(unittest.TestCase):
    """The entry threshold and the exit threshold differ."""

    def test_below_holds_until_clear_of_the_band(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.battery", below=20, hysteresis=5)

        # Entering: has to actually cross the threshold.
        self.assertFalse(evaluate_condition(r, "22", False))
        self.assertTrue(evaluate_condition(r, "19", False))

        # Already active: stays active inside the band (20 to 25).
        self.assertTrue(evaluate_condition(r, "21", True))
        self.assertTrue(evaluate_condition(r, "24.9", True))

        # Clear of the band: releases.
        self.assertFalse(evaluate_condition(r, "25", True))
        self.assertFalse(evaluate_condition(r, "30", True))

    def test_above_holds_until_clear_of_the_band(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.temp", above=80, hysteresis=5)

        self.assertFalse(evaluate_condition(r, "78", False))
        self.assertTrue(evaluate_condition(r, "81", False))

        # Active: stays active down to 75.
        self.assertTrue(evaluate_condition(r, "79", True))
        self.assertTrue(evaluate_condition(r, "75.1", True))
        self.assertFalse(evaluate_condition(r, "75", True))

    def test_zero_hysteresis_matches_plain_threshold(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.x", below=20, hysteresis=0)
        self.assertFalse(evaluate_condition(r, "20", True))

    def test_negative_hysteresis_is_treated_as_magnitude(self) -> None:
        r = rule(kind="numeric", entity_id="sensor.x", below=20, hysteresis=-5)
        self.assertTrue(evaluate_condition(r, "24", True))


class AsBoolTest(unittest.TestCase):
    """Template results arrive in whatever shape the template produced."""

    def test_real_booleans(self) -> None:
        self.assertTrue(as_bool(True))
        self.assertFalse(as_bool(False))

    def test_strings(self) -> None:
        for value in ("true", "True", "on", "yes", "1"):
            self.assertTrue(as_bool(value), value)
        for value in ("false", "off", "no", "0", ""):
            self.assertFalse(as_bool(value), value)

    def test_numbers(self) -> None:
        self.assertTrue(as_bool(1))
        self.assertFalse(as_bool(0))

    def test_unknown_shapes_are_none(self) -> None:
        self.assertIsNone(as_bool(None))
        self.assertIsNone(as_bool("unavailable"))
        self.assertIsNone(as_bool("something else"))


if __name__ == "__main__":
    unittest.main()
