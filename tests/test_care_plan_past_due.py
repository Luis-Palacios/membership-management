"""Care log rule 6: when a plan waits for *Record how it went* (`plan_past_due`)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time

from membership_management.data.care.services import plan_past_due

TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 17, 37)


class PlanPastDueTest(unittest.TestCase):
    def test_earlier_today_with_a_time_is_past_due(self) -> None:
        self.assertTrue(plan_past_due(TODAY, time(15, 0), NOW))

    def test_its_exact_minute_is_past_due(self) -> None:
        self.assertTrue(plan_past_due(TODAY, time(17, 37), NOW))

    def test_later_today_is_not_past_due(self) -> None:
        self.assertFalse(plan_past_due(TODAY, time(18, 0), NOW))

    def test_today_without_a_time_waits_for_tomorrow(self) -> None:
        self.assertFalse(plan_past_due(TODAY, None, NOW))

    def test_an_earlier_day_is_past_due_whatever_the_time(self) -> None:
        self.assertTrue(plan_past_due(date(2026, 11, 23), None, NOW))
        self.assertTrue(plan_past_due(date(2026, 11, 23), time(23, 59), NOW))

    def test_a_later_day_is_not_past_due(self) -> None:
        self.assertFalse(plan_past_due(date(2026, 11, 25), time(0, 0), NOW))


if __name__ == "__main__":
    unittest.main()
