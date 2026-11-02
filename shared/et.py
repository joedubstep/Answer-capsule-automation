"""US Eastern time helpers with no tzdata dependency, plus the twin-fire guard.

Cloud routine crons are UTC. To land on one Eastern wall-clock hour all year, every daily
routine fires twice, one hour apart (e.g. "0 10,11 * * *" for 6am ET). `guard(hour)` says
whether THIS fire is the one that lands on that Eastern hour, so exactly one of the two runs.
"""
import datetime as _dt

UTC = _dt.timezone.utc


def _nth_sunday(year, month, n):
    d = _dt.date(year, month, 1)
    d += _dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + _dt.timedelta(weeks=n - 1)


def et_offset_hours(utc_dt):
    """-4 during US daylight time (2nd Sun Mar 2am to 1st Sun Nov 2am local), else -5."""
    y = utc_dt.year
    start = _dt.datetime.combine(_nth_sunday(y, 3, 2), _dt.time(7, 0), UTC)   # 2am EST = 07:00 UTC
    end = _dt.datetime.combine(_nth_sunday(y, 11, 1), _dt.time(6, 0), UTC)     # 2am EDT = 06:00 UTC
    return -4 if start <= utc_dt < end else -5


def now_utc():
    return _dt.datetime.now(UTC)


def to_et(utc_dt):
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    off = et_offset_hours(utc_dt.astimezone(UTC))
    return utc_dt.astimezone(_dt.timezone(_dt.timedelta(hours=off)))


def now_et():
    return to_et(now_utc())


def et_to_utc(naive_et):
    """Naive Eastern wall time -> aware UTC."""
    guess = naive_et.replace(tzinfo=UTC) + _dt.timedelta(hours=5)
    off = et_offset_hours(guess)
    return (naive_et - _dt.timedelta(hours=off)).replace(tzinfo=UTC)


def parse(ts):
    """ISO string, epoch ms/s int, or None -> aware UTC datetime (or None)."""
    if ts in (None, ""):
        return None
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
        v = float(ts)
        if v > 1e12:
            v /= 1000.0
        return _dt.datetime.fromtimestamp(v, UTC)
    s = str(ts).strip().replace("Z", "+00:00")
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else et_to_utc(d)


def days_since(ts, now=None):
    d = parse(ts)
    if not d:
        return None
    return ((now or now_utc()) - d).total_seconds() / 86400.0


def guard(target_hour_et, now=None):
    """'RUN' if the current Eastern hour equals target_hour_et, else 'SKIP'."""
    return "RUN" if to_et(now or now_utc()).hour == target_hour_et else "SKIP"


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "guard":
        print(guard(int(sys.argv[2])))
    else:
        print(now_et().isoformat())
