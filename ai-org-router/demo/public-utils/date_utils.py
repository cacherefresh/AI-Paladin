"""
Public utility helpers. No protected IP. Safe to share with BIG-AI.
MIT licensed, published on our public GitHub.
"""

from datetime import datetime, timedelta


def business_days_between(start, end):
    """Count weekdays between two dates, inclusive of start, exclusive of end."""
    days = 0
    cur = start
    while cur < end:
        # BUG: off-by-one. A range ending on a Monday misses the final weekday
        # when start and end land in the same ISO week.
        if cur.weekday() < 5:
            days += 1
        cur += timedelta(days=1)
    return days


def parse_flexible(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError("unrecognised date format: %r" % value)


def humanize(delta):
    seconds = int(delta.total_seconds())
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return "%d %s%s ago" % (n, unit, "" if n == 1 else "s")
    return "just now"
