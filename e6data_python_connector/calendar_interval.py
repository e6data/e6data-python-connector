"""Lossless calendar intervals returned by MAKE_INTERVAL."""
from typing import NamedTuple


class CalendarInterval(NamedTuple):
    """Months and calendar days are independent of elapsed microseconds."""

    months: int
    days: int
    microseconds: int

    def __str__(self):
        month_sign = -1 if self.months < 0 else 1
        time_sign = -1 if self.microseconds < 0 else 1
        months = abs(self.months)
        micros = abs(self.microseconds)
        values = (month_sign * (months // 12), month_sign * (months % 12),
                  self.days, time_sign * (micros // 3600000000),
                  time_sign * (micros // 60000000 % 60))
        parts = [f"{value} {unit}" for value, unit in
                 zip(values, ("years", "months", "days", "hours", "minutes")) if value]
        seconds = micros % 60000000
        if seconds:
            whole, fraction = divmod(seconds, 1000000)
            text = str(whole)
            if fraction:
                text += f".{fraction:06d}".rstrip('0')
            parts.append(f"{'-' if time_sign < 0 else ''}{text} seconds")
        return ' '.join(parts) if parts else '0 seconds'
