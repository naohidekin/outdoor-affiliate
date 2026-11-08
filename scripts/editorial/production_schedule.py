"""JST production periods only. Reporting and SEO retain their Monday weeks."""
from datetime import date, datetime, timedelta, timezone
import re

JST = timezone(timedelta(hours=9))


class ProductionSchedule:
    def __init__(self, config=None):
        self.initial = self.effective = None
        self.weekday, self.hour = 2, 9
        if config is None:
            return
        try:
            if not isinstance(config, dict):
                raise ValueError()
            weekday, hour = config['weekday'], config['hour']
            if type(weekday) is not int or not 0 <= weekday <= 6 or type(hour) is not int or not 0 <= hour <= 23:
                raise ValueError()
            effective = config['effectiveFrom']
            if not isinstance(effective, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', effective):
                raise ValueError()
            effective = date.fromisoformat(effective)
            initial = datetime.fromisoformat(config['initialProductionAt'].replace('Z', '+00:00'))
            if initial.tzinfo is None or initial.utcoffset() is None:
                raise ValueError()
            initial = initial.astimezone(JST)
            if effective.weekday() != weekday or initial.date() >= effective:
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise ValueError('invalid productionSchedule') from None
        self.weekday, self.hour = weekday, hour
        self.initial, self.effective = initial, effective

    def period_key(self, now):
        now = self._jst(now)
        if self.initial is None:
            return (now.date() - timedelta(days=now.weekday())).isoformat()
        if now < self.initial:
            return None
        if now.date() < self.effective:
            return (self.initial.date() - timedelta(days=(self.initial.weekday() - self.weekday) % 7)).isoformat()
        start = now.date() - timedelta(days=(now.weekday() - self.weekday) % 7)
        due = datetime.combine(start, datetime.min.time(), JST).replace(hour=self.hour)
        return start.isoformat() if now >= due else None

    def is_due(self, now):
        now = self._jst(now)
        key = self.period_key(now)
        if key is None:
            return False
        if self.initial is not None:
            return True
        return now.weekday() > self.weekday or now.weekday() == self.weekday and now.hour >= self.hour

    @staticmethod
    def _jst(now):
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('aware datetime required')
        return now.astimezone(JST)
