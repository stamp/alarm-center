"""Tests for the alarm lifecycle rules.

Run without Home Assistant installed:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load the modules directly, without running the package __init__ (which
# imports Home Assistant). Relative imports still resolve inside this stub.
_COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "alarm_center"
_pkg = types.ModuleType("_alarm_center")
_pkg.__path__ = [str(_COMPONENT)]
sys.modules["_alarm_center"] = _pkg

AlarmBook = importlib.import_module("_alarm_center.lifecycle").AlarmBook

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    """Timestamp ``minutes`` after T0."""
    return T0 + timedelta(minutes=minutes)


class LifecycleTest(unittest.TestCase):
    """The rules from the spec, one test each."""

    def setUp(self) -> None:
        self.book = AlarmBook()

    def _raise(self, minutes: int = 0, key: str = "rule:test"):
        alarm, created, _became_active = self.book.raise_alarm(
            key, name="Test", level="warning", now=at(minutes)
        )
        return alarm, created

    def test_raise_creates_alarm(self) -> None:
        alarm, created = self._raise()
        self.assertTrue(created)
        self.assertTrue(alarm.active)
        self.assertFalse(alarm.acknowledged)
        self.assertEqual(alarm.activated_at, T0)
        self.assertEqual(alarm.activation_count, 1)

    def test_toggling_without_ack_is_the_same_alarm(self) -> None:
        first, _ = self._raise(0)
        self.book.clear_alarm("rule:test", at(5))
        second, created = self._raise(10)

        self.assertFalse(created)
        self.assertIs(first, second)
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.activated_at, T0, "first activation is kept")
        self.assertEqual(second.last_activated_at, at(10))
        self.assertIsNone(second.deactivated_at)
        self.assertEqual(second.activation_count, 2)
        self.assertEqual(len(self.book.open_alarms), 1)

    def test_repeated_raise_while_active_does_not_count(self) -> None:
        self._raise(0)
        alarm, created = self._raise(1)
        self.assertFalse(created)
        self.assertEqual(alarm.activation_count, 1)

    def test_became_active_flag(self) -> None:
        _alarm, _created, became_active = self.book.raise_alarm(
            "rule:test", name="Test", level="warning", now=at(0)
        )
        self.assertTrue(became_active, "brand new alarm is active")

        _alarm, _created, became_active = self.book.raise_alarm(
            "rule:test", name="Test", level="warning", now=at(1)
        )
        self.assertFalse(became_active, "already active, nothing changed")

        self.book.clear_alarm("rule:test", at(2))
        _alarm, created, became_active = self.book.raise_alarm(
            "rule:test", name="Test", level="warning", now=at(3)
        )
        self.assertFalse(created, "still the same alarm")
        self.assertTrue(became_active, "came back from inactive")

    def test_stays_in_list_when_only_acknowledged(self) -> None:
        alarm, _ = self._raise()
        self.book.acknowledge(alarm.id, user_id="u1", user_name="Stamp", now=at(2))
        self.assertFalse(alarm.archivable)
        self.assertEqual(len(self.book.open_alarms), 1)
        self.assertEqual(alarm.acknowledged_by_name, "Stamp")
        self.assertEqual(alarm.acknowledged_at, at(2))

    def test_stays_in_list_when_only_inactive(self) -> None:
        self._raise()
        self.book.clear_alarm("rule:test", at(3))
        alarm = self.book.get("rule:test")
        self.assertFalse(alarm.active)
        self.assertFalse(alarm.archivable)
        self.assertEqual(alarm.deactivated_at, at(3))

    def test_archives_when_acknowledged_and_inactive(self) -> None:
        alarm, _ = self._raise()
        self.book.acknowledge(alarm.id, user_id="u1", user_name="Stamp", now=at(1))
        self.book.clear_alarm("rule:test", at(2))
        self.assertTrue(alarm.archivable)

        archived = self.book.archive("rule:test", at(3))
        self.assertIsNotNone(archived)
        self.assertEqual(archived.archived_at, at(3))
        self.assertEqual(self.book.open_alarms, [])

    def test_new_alarm_after_archive(self) -> None:
        first, _ = self._raise(0)
        self.book.acknowledge(first.id, now=at(1))
        self.book.clear_alarm("rule:test", at(2))
        self.book.archive("rule:test", at(3))

        second, created = self._raise(10)
        self.assertTrue(created)
        self.assertNotEqual(second.id, first.id)
        self.assertFalse(second.acknowledged)
        self.assertEqual(second.activation_count, 1)

    def test_acknowledge_twice_is_noop(self) -> None:
        alarm, _ = self._raise()
        self.assertIsNotNone(self.book.acknowledge(alarm.id, now=at(1)))
        self.assertIsNone(self.book.acknowledge(alarm.id, now=at(2)))

    def test_became_active_survives_acknowledgement(self) -> None:
        """An acked alarm that flaps is still a fresh activation event.

        Notifications and on_activate actions key off became_active, so this
        is what decides whether an acknowledged-but-still-open alarm alerts
        again when the fault returns.
        """
        alarm, _, _ = self.book.raise_alarm(
            "rule:test", name="Test", level="warning", now=at(0)
        )
        self.book.acknowledge(alarm.id, now=at(1))
        self.book.clear_alarm("rule:test", at(2))

        _alarm, created, became_active = self.book.raise_alarm(
            "rule:test", name="Test", level="warning", now=at(3)
        )
        self.assertFalse(created)
        self.assertTrue(became_active)
        self.assertTrue(alarm.acknowledged, "acknowledgement is not reset")

    def test_clear_unknown_key(self) -> None:
        self.assertIsNone(self.book.clear_alarm("rule:nope", at(1)))

    def test_counts(self) -> None:
        a1, _ = self._raise(0, key="rule:a")
        self._raise(0, key="rule:b")
        self.book.acknowledge(a1.id, now=at(1))
        self.book.clear_alarm("rule:b", at(1))

        self.assertEqual(self.book.count(), 2)
        self.assertEqual(self.book.count(active=True), 1)
        self.assertEqual(self.book.count(acknowledged=False), 1)

    def test_roundtrip_through_storage(self) -> None:
        alarm, _ = self._raise()
        self.book.acknowledge(alarm.id, user_id="u1", user_name="Stamp", now=at(1))

        restored = AlarmBook()
        restored.load(self.book.as_list())
        copy = restored.get("rule:test")

        self.assertEqual(copy.id, alarm.id)
        self.assertTrue(copy.acknowledged)
        self.assertEqual(copy.acknowledged_by_name, "Stamp")
        self.assertEqual(copy.activated_at, T0)

    def test_sorting_puts_unacked_and_severe_first(self) -> None:
        self.book.raise_alarm("a", name="A", level="notice", now=at(0))
        self.book.raise_alarm("b", name="B", level="critical", now=at(1))
        acked, _created, _became_active = self.book.raise_alarm(
            "c", name="C", level="critical", now=at(2)
        )
        self.book.acknowledge(acked.id, now=at(3))

        order = [alarm.name for alarm in self.book.open_alarms]
        self.assertEqual(order, ["B", "A", "C"])


if __name__ == "__main__":
    unittest.main()
