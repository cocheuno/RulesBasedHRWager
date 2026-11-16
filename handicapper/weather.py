"""Weather as a source observation (Phase B).  Two kinds, both kept with provenance, neither read by a rule yet:

* fetched: ``python-weather`` (wttr.in) forecast for the track's location, one observation per race post time
  (nearest hourly forecast).  Optional: no network, no package or no location gives ``{"status": "unavailable"}``,
  never a guess.  Tests replay a fixture through ``observations_from_forecast``.
* manual: the owner types the weather ("Light Rain / Wind NW at 13 mph Temperature 44°F / Humidity 82%", any line
  order); ``parse_manual`` reads it into the same shape with provenance ``manual``.

``latest_before(observations, cutoff_utc)`` is the one a rule may read for a race: the most recent observation made
at or before that race's cutoff.  Manual and fetched observations never overwrite each other.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

PROVIDER = "python-weather (wttr.in)"
FETCH_TIMEOUT_S = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def observation(*, provenance: str, condition=None, wind_direction=None, wind_mph=None, temperature_f=None, humidity_pct=None,
                precipitation_in=None, forecast_for_utc=None, observed_at_utc=None, location=None, text=None, provider=None) -> dict:
    return {"provenance": provenance, "provider": provider or (PROVIDER if provenance == "fetched" else "owner"),
            "observed_at_utc": observed_at_utc or utc_now(), "forecast_for_utc": forecast_for_utc, "location": location,
            "condition": condition, "wind_direction": wind_direction, "wind_mph": wind_mph, "temperature_f": temperature_f,
            "humidity_pct": humidity_pct, "precipitation_in": precipitation_in, "text": text}


# ---------------------------------------------------------------------------
# Manual entry
# ---------------------------------------------------------------------------
WIND_RE = re.compile(r"wind\s*:?\s*(?P<dir>[NSEW]{1,3}|calm|variable)?\s*(?:at|@)?\s*(?P<spd>\d+(?:\.\d+)?)?\s*(?P<unit>mph|km/?h|kph|kt|knots)?", re.I)
TEMP_RE = re.compile(r"temp(?:erature)?\s*:?\s*(?P<t>-?\d+(?:\.\d+)?)\s*°?\s*(?P<u>[FC])?\b", re.I)
HUM_RE = re.compile(r"humidity\s*:?\s*(?P<h>\d+)\s*%?", re.I)
PRECIP_RE = re.compile(r"(?:precip(?:itation)?|rain(?:fall)?)\s*:?\s*(?P<p>\d+(?:\.\d+)?)\s*(?P<u>in(?:ch(?:es)?)?|mm)\b", re.I)
CONDITION_WORDS = ["light rain", "heavy rain", "rain", "showers", "drizzle", "thunderstorm", "snow", "sleet", "fog", "mist", "haze",
                   "overcast", "mostly cloudy", "partly cloudy", "cloudy", "clear", "sunny", "fair", "windy"]


def parse_manual(text: str, observed_at_utc: str | None = None, location: str | None = None) -> dict:
    """Owner-typed weather in any line order.  Unreadable parts stay None; the text itself is kept."""
    t = " ".join((text or "").replace("\n", " / ").split())
    obs = observation(provenance="manual", observed_at_utc=observed_at_utc, location=location, text=text)
    low = t.lower()
    for w in CONDITION_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            obs["condition"] = w.title()
            break
    m = WIND_RE.search(t)
    if m and (m.group("dir") or m.group("spd")):
        obs["wind_direction"] = (m.group("dir") or "").upper() or None
        if m.group("spd"):
            spd = float(m.group("spd"))
            unit = (m.group("unit") or "mph").lower()
            if unit.startswith("km") or unit == "kph":
                spd *= 0.621371
            elif unit.startswith("kt") or unit.startswith("kn"):
                spd *= 1.15078
            obs["wind_mph"] = round(spd, 1)
    m = TEMP_RE.search(t)
    if m:
        v = float(m.group("t"))
        obs["temperature_f"] = round(v * 9 / 5 + 32, 1) if (m.group("u") or "F").upper() == "C" else v
    m = HUM_RE.search(t)
    if m:
        obs["humidity_pct"] = int(m.group("h"))
    m = PRECIP_RE.search(t)
    if m:
        v = float(m.group("p"))
        obs["precipitation_in"] = round(v / 25.4, 2) if m.group("u").lower().startswith("mm") else v
    return obs


# ---------------------------------------------------------------------------
# Fetched forecast
# ---------------------------------------------------------------------------
def _parse_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def observations_from_forecast(forecast: dict, post_times_utc: dict, tz: str | None, location: str | None,
                               fetched_at_utc: str | None = None) -> list[dict]:
    """forecast: {"daily": [{"date": "YYYY-MM-DD", "hourly": [{"time": "HH:MM", "description", "wind_direction",
    "wind_mph", "temperature_f", "humidity_pct", "precipitation_in"}]}]} (the replayable shape python-weather is
    reduced to).  post_times_utc: {race_no: "…Z"}.  One observation per race: the hourly forecast nearest its post
    time in the track's local time."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz) if tz else timezone.utc
    hours = []
    for day in forecast.get("daily", []):
        for h in day.get("hourly", []):
            try:
                local = datetime.fromisoformat(f"{day['date']}T{h['time']}:00").replace(tzinfo=zone)
            except (KeyError, ValueError):
                continue
            hours.append((local.astimezone(timezone.utc), h))
    out = []
    for rn, post in sorted(post_times_utc.items(), key=lambda kv: int(kv[0])):
        p = _parse_utc(post)
        if not p or not hours:
            continue
        when, h = min(hours, key=lambda x: abs(x[0] - p))
        if abs(when - p) > timedelta(hours=3):
            continue
        obs = observation(provenance="fetched", observed_at_utc=fetched_at_utc, forecast_for_utc=when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                          location=location, condition=h.get("description"), wind_direction=h.get("wind_direction"),
                          wind_mph=h.get("wind_mph"), temperature_f=h.get("temperature_f"), humidity_pct=h.get("humidity_pct"),
                          precipitation_in=h.get("precipitation_in"))
        obs["race_no"] = int(rn)
        out.append(obs)
    return out


def _reduce(fc) -> dict:
    """python-weather Forecast -> the replayable dict (imperial units requested at fetch time)."""
    daily = []
    for d in getattr(fc, "daily_forecasts", None) or getattr(fc, "forecasts", []) or []:
        hourly = []
        for h in getattr(d, "hourly_forecasts", None) or getattr(d, "hourly", []) or []:
            t = getattr(h, "time", None)
            wd = getattr(h, "wind_direction", None)
            hourly.append({"time": t.strftime("%H:%M") if hasattr(t, "strftime") else str(t), "description": getattr(h, "description", None),
                           "wind_direction": getattr(wd, "name", None) if wd is not None and not isinstance(wd, str) else wd,
                           "wind_mph": getattr(h, "wind_speed", None), "temperature_f": getattr(h, "temperature", None),
                           "humidity_pct": getattr(h, "humidity", None), "precipitation_in": getattr(h, "precipitation", None)})
        daily.append({"date": str(getattr(d, "date", "")), "hourly": hourly})
    return {"daily": daily}


def fetch(location: str, post_times_utc: dict, tz: str | None, timeout_s: float = FETCH_TIMEOUT_S) -> dict:
    """Fetch the forecast for ``location`` and return {"status": "ok", "observations": [...], "forecast": reduced} or
    {"status": "unavailable", "reason": ...}.  Never raises; never guesses."""
    if not location:
        return {"status": "unavailable", "reason": "no location configured for this track (rules_config.json tracks.<code>.location)"}
    if not post_times_utc:
        return {"status": "unavailable", "reason": "no post times to forecast for"}
    try:
        import asyncio
        import python_weather
    except ImportError as e:
        return {"status": "unavailable", "reason": f"python-weather not installed ({e})"}

    async def go():
        async with python_weather.Client(unit=python_weather.IMPERIAL) as client:
            return await asyncio.wait_for(client.get(location), timeout=timeout_s)

    try:
        fc = asyncio.run(go())
    except Exception as e:   # network, DNS, proxy, timeout, provider error: all "unavailable"
        return {"status": "unavailable", "reason": f"{type(e).__name__}: {e}"[:200]}
    fetched_at = utc_now()
    reduced = _reduce(fc)
    obs = observations_from_forecast(reduced, post_times_utc, tz, location, fetched_at)
    return {"status": "ok" if obs else "unavailable", "reason": None if obs else "forecast did not cover the post times",
            "fetched_at_utc": fetched_at, "provider": PROVIDER, "location": location, "observations": obs, "forecast": reduced}


def latest_before(observations: list[dict], cutoff_utc: str | None, race_no: int | None = None) -> dict | None:
    """The most recent observation (fetched for this race, or manual) made at or before the cutoff."""
    cut = _parse_utc(cutoff_utc)
    best = None
    for o in observations or []:
        if o.get("race_no") not in (None, race_no):
            continue
        at = _parse_utc(o.get("observed_at_utc"))
        if at is None or (cut is not None and at > cut):
            continue
        if best is None or at >= _parse_utc(best["observed_at_utc"]):
            best = o
    return best


def summary_text(o: dict | None) -> str:
    if not o:
        return "weather: unavailable"
    parts = [o.get("condition")]
    if o.get("wind_mph") is not None or o.get("wind_direction"):
        parts.append(f"wind {o.get('wind_direction') or ''} {o['wind_mph']:.0f} mph".replace("  ", " ") if o.get("wind_mph") is not None else f"wind {o['wind_direction']}")
    if o.get("temperature_f") is not None:
        parts.append(f"{o['temperature_f']:.0f}°F")
    if o.get("humidity_pct") is not None:
        parts.append(f"humidity {o['humidity_pct']}%")
    return ", ".join(p for p in parts if p) + f" ({o.get('provenance')})"
