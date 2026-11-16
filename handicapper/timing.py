"""
Per-race timing: when was a run made relative to each race's wagering cutoff?

Brisnet prints every race's post time in four zones, "(12:20)/11:20/10:20/ 9:20" = Eastern, Central, Mountain,
Pacific, with the track's local zone in brackets.  The Eastern value and America/New_York give the instant, so
no timezone guess is needed for the scheduled post.  A chart gives the actual off time in the track's local
zone ("1:02"); that needs the track's timezone (rules_config.json -> tracks.<code>.timezone) and, when known, it
is the authoritative cutoff.  A run is `before-cutoff` for a race when it was made at least `cutoff_margin_minutes`
before the cutoff, `after-cutoff` otherwise, `unknown` when no post or off time can be established.  Nothing
here asks the owner to type a time.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMING = {"cutoff_margin_minutes": 2}
EASTERN = "America/New_York"
POST_RE = re.compile(r"\(?\s*(\d{1,2}):(\d{2})\s*\)?")


def _clock_to_hours(h: int, m: int) -> tuple[int, int]:
    """Racing clocks are 12-hour without AM/PM: 10 and 11 are morning, 12 and 1-9 are afternoon/evening."""
    if h in (10, 11):
        return h, m
    return (12 if h == 12 else h + 12), m


def post_at_utc(card_date: str, post_time_text: str | None) -> datetime | None:
    """Scheduled post as a UTC datetime from the Brisnet four-zone string (first value = Eastern)."""
    if not card_date or not post_time_text:
        return None
    parts = POST_RE.findall(post_time_text)
    if not parts:
        return None
    h, m = _clock_to_hours(int(parts[0][0]), int(parts[0][1]))
    try:
        local = datetime.fromisoformat(card_date).replace(hour=h, minute=m, tzinfo=ZoneInfo(EASTERN))
    except (ValueError, TypeError):
        return None
    return local.astimezone(timezone.utc)


def off_at_utc(card_date: str, off_at_text: str | None, tz: str | None) -> datetime | None:
    """Actual off time from a chart ("1:02", track local) as UTC; None without a track timezone."""
    if not card_date or not off_at_text or not tz:
        return None
    m = POST_RE.search(off_at_text)
    if not m:
        return None
    h, mi = _clock_to_hours(int(m.group(1)), int(m.group(2)))
    try:
        local = datetime.fromisoformat(card_date).replace(hour=h, minute=mi, tzinfo=ZoneInfo(tz))
    except (ValueError, TypeError, KeyError):
        return None
    return local.astimezone(timezone.utc)


def parse_utc(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def cutoff_status(run_at: datetime | None, cutoff: datetime | None, margin_minutes: float) -> str:
    if run_at is None or cutoff is None:
        return "unknown"
    return "before-cutoff" if run_at <= cutoff - timedelta(minutes=margin_minutes) else "after-cutoff"


def race_cutoffs(card_date: str, races: list[dict], run_at: datetime | None, margin_minutes: float,
                 results_by_no: dict | None = None, tz: str | None = None) -> dict:
    """{race_no: {post_at_utc, off_at_utc, cutoff_at_utc, basis, status}} for a run made at run_at.
    Basis "off" when the chart's off time is known (authoritative), else "scheduled", else "none"."""
    out = {}
    for r in races:
        rn = r["race_no"]
        post = post_at_utc(card_date, r.get("post_time"))
        res = (results_by_no or {}).get(rn) or {}
        off = off_at_utc(card_date, res.get("off_at"), tz) if res else None
        cutoff = off or post
        out[str(rn)] = {"post_at_utc": post.isoformat() if post else None, "off_at_utc": off.isoformat() if off else None,
                        "cutoff_at_utc": cutoff.isoformat() if cutoff else None,
                        "basis": "off" if off else ("scheduled" if post else "none"),
                        "status": cutoff_status(run_at, cutoff, margin_minutes)}
    return out


def timing_summary(cutoffs: dict) -> dict:
    st = [c["status"] for c in cutoffs.values()]
    return {"races": len(st), "before": st.count("before-cutoff"), "after": st.count("after-cutoff"), "unknown": st.count("unknown"),
            "label": ("verified" if st and all(s == "before-cutoff" for s in st) else
                      "unverified" if not st or all(s == "unknown" for s in st) else "mixed")}
