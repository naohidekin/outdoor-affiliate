"""Offline production period boundaries; reporting weeks are independent."""
from datetime import datetime
import unittest

from production_schedule import ProductionSchedule

SCHEDULE = dict(weekday=4, hour=9, effectiveFrom='2026-11-13',
                initialProductionAt='2026-11-08T00:00:00+09:00')


class ProductionScheduleTests(unittest.TestCase):
    def test_transition_and_utc_boundaries(self):
        schedule = ProductionSchedule(SCHEDULE)
        cases = [
            ('2026-11-07T23:59:59+09:00', None, False),
            ('2026-11-07T14:59:59Z', None, False),
            ('2026-11-07T15:00:00Z', '2026-11-06', True),
            ('2026-11-08T00:00:00+09:00', '2026-11-06', True),
            ('2026-11-09T09:00:00+09:00', '2026-11-06', True),
            ('2026-11-11T09:00:00+09:00', '2026-11-06', True),
            ('2026-11-12T23:59:59+09:00', '2026-11-06', True),
            ('2026-11-12T15:00:00Z', None, False),
            ('2026-11-12T23:59:59Z', None, False),
            ('2026-11-13T00:00:00Z', '2026-11-13', True),
            ('2026-11-16T09:00:00+09:00', '2026-11-13', True),
            ('2026-11-19T23:59:59+09:00', '2026-11-13', True),
            ('2026-11-20T08:59:59+09:00', None, False),
            ('2026-11-20T09:00:00+09:00', '2026-11-20', True),
        ]
        for value, period, due in cases:
            with self.subTest(value=value):
                now = datetime.fromisoformat(value.replace('Z', '+00:00'))
                self.assertEqual(period, schedule.period_key(now))
                self.assertEqual(due, schedule.is_due(now))

    def test_legacy_monday_period_and_wednesday_due(self):
        schedule = ProductionSchedule()
        for day, hour, due in ((9, 9, False), (11, 8, False), (11, 9, True),
                               (13, 9, True), (15, 23, True), (16, 9, False)):
            now = datetime.fromisoformat(f'2026-11-{day:02}T{hour:02}:00:00+09:00')
            self.assertEqual('2026-11-16' if day == 16 else '2026-11-09', schedule.period_key(now))
            self.assertEqual(due, schedule.is_due(now))

    def test_invalid_settings_fail_closed(self):
        invalid = [{}, [], False, 'Friday',
                   *[dict(SCHEDULE, **change) for change in (
                       {'weekday': True}, {'weekday': -1}, {'weekday': 7}, {'weekday': '4'},
                       {'hour': True}, {'hour': 24}, {'hour': -1}, {'hour': 9.0},
                       {'effectiveFrom': '2026-11-12'}, {'effectiveFrom': '2026-02-30'},
                       {'effectiveFrom': '20261113'}, {'initialProductionAt': '2026-11-09T09:00:00'},
                       {'initialProductionAt': '2026-11-13T09:00:00+09:00'},
                       {'initialProductionAt': None})]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ProductionSchedule(value)
