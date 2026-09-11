"""Tests for quiet-hours time windows.

Run without Home Assistant installed:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import time
from pathlib import Path

_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "alarm_center"
if "_alarm_center" not in sys.modules:
    _pkg = types.ModuleType("_alarm_center")
    _pkg.__path__ = [str(_COMPONENT)]
    sys.modules["_alarm_center"] = _pkg

_schedule = importlib.import_module("_alarm_center.schedule")
in_window = _schedule.in_window
parse_hhmm = _schedule.parse_hhmm


class ParseTest(unittest.TestCase):
    """Times come from a text field, so they arrive in any shape."""

    def test_normal(self) -> None:
        self.assertEqual(parse_hhmm("22:00"), (22, 0))
        self.assertEqual(parse_hhmm("7:05"), (7, 5))
        self.assertEqual(parse_hhmm("00:00"), (0, 0))

    def test_hour_only(self) -> None:
        self.assertEqual(parse_hhmm("22"), (22, 0))

    def test_junk_falls_back(self) -> None:
        for value in (None, "", "nonsense", "25:00", "12:99", "-1:00", "::"):
            self.assertEqual(parse_hhmm(value, (7, 0)), (7, 0), value)


class WindowTest(unittest.TestCase):
    """The normal case for quiet hours wraps past midnight."""

    def test_overnight_window(self) -> None:
        start, end = "22:00", "07:00"

        for hour in (22, 23, 0, 3, 6):
            self.assertTrue(in_window(time(hour, 30), start, end), hour)
        for hour in (7, 8, 12, 21):
            self.assertFalse(in_window(time(hour, 30), start, end), hour)

    def test_boundaries(self) -> None:
        start, end = "22:00", "07:00"
        self.assertTrue(in_window(time(22, 0), start, end), "start is inclusive")
        self.assertFalse(in_window(time(7, 0), start, end), "end is exclusive")
        self.assertTrue(in_window(time(6, 59), start, end))

    def test_same_day_window(self) -> None:
        start, end = "09:00", "17:00"
        self.assertTrue(in_window(time(12, 0), start, end))
        self.assertFalse(in_window(time(8, 59), start, end))
        self.assertFalse(in_window(time(17, 0), start, end))
        self.assertFalse(in_window(time(23, 0), start, end))

    def test_equal_ends_is_empty_not_always(self) -> None:
        """Guards against a typo silencing every alarm forever."""
        for hour in (0, 8, 12, 23):
            self.assertFalse(in_window(time(hour, 0), "08:00", "08:00"), hour)

    def test_minutes_matter(self) -> None:
        self.assertTrue(in_window(time(22, 30), "22:15", "07:00"))
        self.assertFalse(in_window(time(22, 10), "22:15", "07:00"))


if __name__ == "__main__":
    unittest.main()
