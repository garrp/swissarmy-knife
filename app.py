# app.py
# Kayak Wind Advisor (Streamlit)
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional, Tuple

import math
import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "1.0.5"

# Pacific Northwest scope (edit if you want to expand)
PNW_COUNTRY_CODE = "US"
PNW_ALLOWED_STATES = {"Washington", "Oregon", "Idaho", "Montana"}

# Bias defaults: North Idaho + Eastern WA
CDA_LAT = 47.6777
CDA_LON = -116.7805
EASTERN_WA_LON_MIN = -121.5  # rough Cascades split

# Lock display timezone for PNW
FORECAST_TIMEZONE = "America/Los_Angeles"

# Always use mph
WIND_UNIT = "mph"


# ----------------------------
# Helpers
# ----------------------------
def http_get_json(url: str, params: dict, timeout: int = 20) -> dict:
    try:
        r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "KayakWindAdvisor/1.0"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}")


def deg_to_compass(deg: float) -> str:
    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    i = int((deg / 22.5) + 0.5) % 16
    return dirs[i]


def safe_float_list(x) -> List[float]:
    if x is None:
        return []
    return [float(v) if v is not None else float("nan") for v in x]


def status_color(status: str) -> str:
    if status == "GO":
        return "#1b8f3a"
    if status == "CAUTION":
        return "#c08a00"
    return "#b00020"


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613  # Earth radius in miles
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


def region_rank(lat: float, lon: float, admin1: str) -> int:
    """
    Lower is better (rank).
    0: North Idaho (Idaho + lat >= 46)
    1: Eastern WA (Washington + lon >= EASTERN_WA_LON_MIN)
    2: Other Idaho
    3: Other Washington
    4: Montana
    5: Oregon
    9: Everything else (should not happen due to filtering)
    """
    a = (admin1 or "").strip()
    if a == "Idaho":
        if lat >= 46.0:
            return 0
        return 2
    if a == "Washington":
        if lon >= EASTERN_WA_LON_MIN:
            return 1
        return 3
    if a == "Montana":
        return 4
    if a == "Oregon":
        return 5
    return 9


def sort_results_bias(results: List[dict]) -> List[dict]:
    """
    Sort by:
      1) Region rank (North Idaho + Eastern WA first)
      2) Distance to Coeur d'Alene (closer first)
      3) Population (higher first, if present)
    """
    scored: List[Tuple[Tuple[int, float, int], dict]] = []
    for r in results:
        try:
            lat = float(r.get("latitude", 0.0))
            lon = float(r.get("longitude", 0.0))
        except Exception:
            lat = 0.0
            lon = 0.0

        admin1 = (r.get("admin1") or "").strip()
        rank = region_rank(lat, lon, admin1)
        dist = haversine_miles(CDA_LAT, CDA_LON, lat, lon)

        pop = r.get("population")
        try:
            pop_i = int(pop) if pop is not None else 0
        except Exception:
            pop_i = 0

        scored.append(((rank, dist, -pop_i), r))

    scored.sort(key=lambda x: x[0])
    return [r for _, r in scored]


def geocode_place_pnw(place: str) -> List[dict]:
    """
    Open-Meteo geocoding, filtered to PNW states, then sorted with a bias
    toward North Idaho + Eastern Washington (and closer to Coeur d'Alene).
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": place, "count": 15, "language": "en", "format": "json"}
    data = http_get_json(url, params=params)
    results = data.get("results") or []

    filtered = []
    for r in results:
        country_code = (r.get("country_code") or "").strip()
        admin1 = (r.get("admin1") or "").strip()
        if country_code == PNW_COUNTRY_CODE and admin1 in PNW_ALLOWED_STATES:
            filtered.append(r)

    return sort_results_bias(filtered)


def reverse_geocode_pnw(lat: float, lon: float) -> Optional[dict]:
    url = "https://geocoding-api.open-meteo.com/v1/reverse"
    params = {"latitude": lat, "longitude": lon, "language": "en", "format": "json"}
    data = http_get_json(url, params=params)
    results = data.get("results") or []
    if not results:
        return None

    r = results[0]
    country_code = (r.get("country_code") or "").strip()
    admin1 = (r.get("admin1") or "").strip()
    if country_code == PNW_COUNTRY_CODE and admin1 in PNW_ALLOWED_STATES:
        return r
    return None


def fetch_forecast(lat: float, lon: float) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": FORECAST_TIMEZONE,
        "windspeed_unit": WIND_UNIT,  # always mph
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "hourly": ",".join(
            [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "wind_gusts_10m",
                "wind_direction_10m",
            ]
        ),
        "daily": ",".join(
            [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "precipitation_sum",
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
                "wind_direction_10m_dominant",
                "sunrise",
                "sunset",
            ]
        ),
        "forecast_days": 7,
    }
    return http_get_json(url, params=params)


def filter_to_day(hourly: dict, target: date) -> dict:
    times = hourly.get("time") or []
    out = {}
    idx = []
    for i, t in enumerate(times):
        try:
            d = datetime.fromisoformat(t).date()
        except Exception:
            continue
        if d == target:
            idx.append(i)

    for k, v in hourly.items():
        if k == "time":
            out["time"] = [times[i] for i in idx]
        else:
            if isinstance(v, list):
                out[k] = [v[i] for i in idx]
    return out


def compute_status(sustained_mph: float, gust_mph: float, offshore: bool, big_water: bool) -> str:
    # Fixed, conservative thresholds (no end-user tuning)
    # GO: sustained 0-10 and gust <= 15
    # CAUTION: sustained 11-15 or gust 16-22
    # DO NOT GO: sustained >= 16 or gust >= 23
    status = "GO"
    if sustained_mph >= 16 or gust_mph >= 23:
        status = "DO NOT GO"
    elif sustained_mph >= 11 or gust_mph >= 16:
        status = "CAUTION"

    # Optional bumpers (OFF by default in UI)
    if status != "DO NOT GO":
        if offshore:
            status = "CAUTION" if status == "GO" else "DO NOT GO"
        if big_water:
            status = "CAUTION" if status == "GO" else "DO NOT GO"

    return status


def worst_3hr_window(times: List[str], sustained_mph: List[float], gusts_mph: List[float]) -> Optional[dict]:
    n = min(len(times), len(sustained_mph), len(gusts_mph))
    if n < 3:
        return None

    best = None
    for i in range(n - 2):
        window_s = sustained_mph[i : i + 3]
        window_g = gusts_mph[i : i + 3]
        if any((v != v) for v in window_s) or any((v != v) for v in window_g):
            continue

        scores = []
        for s, g in zip(window_s, window_g):
            gustiness = max(0.0, g - s)
            scores.append(4.0 * s + 2.0 * gustiness)

        avg = sum(scores) / 3.0
        if (best is None) or (avg > best["avg_score"]):
            best = {
                "start": times[i],
                "end": times[i + 2],
                "avg_score": avg,
                "sustained_avg": sum(window_s) / 3.0,
                "gust_avg": sum(window_g) / 3.0,
            }
    return best


# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Kayak Wind Advisor", layout="centered")

st.title("Kayak Wind Advisor")
st.caption(f"Version {APP_VERSION}. PNW only (WA, OR, ID, MT). Biased to North Idaho + Eastern WA.")

# Location first
st.subheader("Location")
use_my_location = st.checkbox("Use my current location", value=True)

st.caption("If current location is blocked or outside the PNW filter, search by name below.")
place_query = st.text_input("Search by place name (fallback)", value="")

# Calendar only (no separate Date header)
target_day = st.date_input("Choose a date", value=date.today())

# Options: do NOT assume big water
st.subheader("Options")
opt1, opt2 = st.columns(2)
with opt1:
    offshore = st.checkbox("Offshore wind risk (more conservative)", value=False)
with opt2:
    big_water = st.checkbox("Big water (large lake, long fetch)", value=False)

st.caption(f"Forecast timezone locked to {FORECAST_TIMEZONE} (PNW local display).")

# --- Browser geolocation (best effort) ---
lat = None
lon = None

if use_my_location:
    components.html(
        """
<script>
(async () => {
  try {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      const lat = pos.coords.latitude.toFixed(6);
      const lon = pos.coords.longitude.toFixed(6);
      const url = new URL(window.location.href);
      url.searchParams.set("lat", lat);
      url.searchParams.set("lon", lon);
      window.history.replaceState({}, "", url);
    });
  } catch (e) {}
})();
</script>
""",
        height=0,
    )

    q = st.query_params
    try:
        if "lat" in q and "lon" in q:
            lat = float(q["lat"])
            lon = float(q["lon"])
    except Exception:
        lat = None
        lon = None

# Resolve final location choice
chosen_r = None
chosen_label = None

try:
    # 1) Try current location (if available)
    if lat is not None and lon is not None:
        rev = reverse_geocode_pnw(lat, lon)
        if rev is not None:
            chosen_r = rev
            chosen_label = f"{rev.get('name','')}, {rev.get('admin1','')}, {rev.get('country','')}"
        else:
            st.warning("Current location not confirmed in WA/OR/ID/MT. Use the search box below.")
            lat = None
            lon = None

    # 2) Fallback to search by name (auto-pick best result; no selectbox)
    if chosen_r is None:
        if not place_query.strip():
            st.info("Enter a place name to search (example: Coeur d'Alene, Hayden, Post Falls, Spokane Valley).")
            st.stop()

        results = geocode_place_pnw(place_query.strip())
        if not results:
            allowed = ", ".join(sorted(list(PNW_ALLOWED_STATES)))
            st.error(
                "No PNW matches found. Try a nearby town name.\n\n"
                f"Allowed area: {PNW_COUNTRY_CODE} only, states: {allowed}."
            )
            st.stop()

        # Auto-pick the top ranked result (already biased + sorted)
        chosen_r = results[0]
        rlat = float(chosen_r.get("latitude", 0.0))
        rlon = float(chosen_r.get("longitude", 0.0))
        dist = haversine_miles(CDA_LAT, CDA_LON, rlat, rlon)

        chosen_label = f"{chosen_r.get('name','')}, {chosen_r.get('admin1','')}, {chosen_r.get('country','')}"
        st.caption(f"Using best match: {chosen_label} ({int(round(dist))} mi from CDA)")

    # Now we have lat/lon
    lat = float(chosen_r["latitude"])
    lon = float(chosen_r["longitude"])

    # Fetch forecast (mph)
    forecast = fetch_forecast(lat, lon)
    hourly = forecast.get("hourly") or {}
    daily = forecast.get("daily") or {}

    hourly_day = filter_to_day(hourly, target_day)

    times = hourly_day.get("time") or []
    sustained_raw = safe_float_list(hourly_day.get("wind_speed_10m"))
    gusts_raw = safe_float_list(hourly_day.get("wind_gusts_10m"))
    dirs_raw = safe_float_list(hourly_day.get("wind_direction_10m"))

    if not times:
        st.warning("No hourly data returned for that date. Try another date or location.")
        st.stop()

    # Day-level status: worst hour (conservative)
    rank_map = {"GO": 0, "CAUTION": 1, "DO NOT GO": 2}
    worst_status = "GO"
    worst_i = 0
    worst_score = -1
    worst_reason = ""

    for i in range(len(times)):
        s = sustained_raw[i]
        g = gusts_raw[i]
        d = dirs_raw[i]
        if s != s or g != g or d != d:
            continue

        st_i = compute_status(s, g, offshore=offshore, big_water=big_water)

        gustiness = max(0.0, g - s)
        score = int(round(4.0 * s + 2.0 * gustiness))
        if offshore:
            score += 10
        if big_water:
            score += 8

        if (rank_map[st_i] > rank_map[worst_status]) or (
            rank_map[st_i] == rank_map[worst_status] and score > worst_score
        ):
            worst_status = st_i
            worst_i = i
            worst_score = score
            worst_reason = f"Sustained {int(round(s))} mph, gusts {int(round(g))} mph."

    # Top decision card
    st.markdown(
        f"""
<div style="border-radius:16px; padding:16px; border:1px solid rgba(0,0,0,0.08);">
  <div style="font-size:14px; opacity:0.8;">{chosen_label}</div>
  <div style="font-size:34px; font-weight:700; color:{status_color(worst_status)}; margin-top:6px;">{worst_status}</div>
  <div style="font-size:16px; margin-top:6px;">{worst_reason}</div>
  <div style="font-size:13px; opacity:0.75; margin-top:8px;">
    Worst hour: {times[worst_i].replace("T", " ")} ({deg_to_compass(dirs_raw[worst_i])}).
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Daily summary row
    daily_time = daily.get("time") or []
    daily_idx = None
    for i, t in enumerate(daily_time):
        try:
            if date.fromisoformat(t) == target_day:
                daily_idx = i
                break
        except Exception:
            continue

    c1, c2, c3, c4 = st.columns(4)
    if daily_idx is not None:
        tmax = (daily.get("temperature_2m_max") or [None])[daily_idx]
        tmin = (daily.get("temperature_2m_min") or [None])[daily_idx]
        pop = (daily.get("precipitation_probability_max") or [None])[daily_idx]
        psum = (daily.get("precipitation_sum") or [None])[daily_idx]
        wmax = (daily.get("wind_speed_10m_max") or [None])[daily_idx]
        gmax = (daily.get("wind_gusts_10m_max") or [None])[daily_idx]
        wdir = (daily.get("wind_direction_10m_dominant") or [None])[daily_idx]
        sunrise = (daily.get("sunrise") or [None])[daily_idx]
        sunset = (daily.get("sunset") or [None])[daily_idx]

        c1.metric("Temp", f"{int(round(tmax))}/{int(round(tmin))} F" if tmax is not None and tmin is not None else "n/a")
        c2.metric("Precip", f"{int(pop)}% ({float(psum):.2f} in)" if pop is not None and psum is not None else "n/a")
        c3.metric("Max wind", f"{int(round(wmax))} mph" if wmax is not None else "n/a")
        if gmax is not None and wdir is not None:
            c4.metric("Max gust", f"{int(round(gmax))} mph ({deg_to_compass(float(wdir))})")
        else:
            c4.metric("Max gust", "n/a")

        if sunrise and sunset:
            st.caption(f"Sunrise {sunrise.replace('T',' ')} | Sunset {sunset.replace('T',' ')} (local time)")

    st.subheader("Wind focus (hourly) - mph")
    rows = []
    for i in range(len(times)):
        s = sustained_raw[i]
        g = gusts_raw[i]
        d = dirs_raw[i]
        if s != s or g != g or d != d:
            continue

        rating = compute_status(s, g, offshore=offshore, big_water=big_water)

        rows.append(
            {
                "Time": times[i].replace("T", " "),
                "Wind (mph)": f"{int(round(s))}",
                "Gust (mph)": f"{int(round(g))}",
                "Dir": f"{deg_to_compass(d)} ({int(round(d))} deg)",
                "Rating": rating,
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Wind chart (mph)")
    import pandas as pd

    chart_df = pd.DataFrame(
        {
            "time": [t.replace("T", " ") for t in times],
            "wind_speed_mph": sustained_raw[: len(times)],
            "wind_gusts_mph": gusts_raw[: len(times)],
        }
    ).set_index("time")
    st.line_chart(chart_df)

    ww = worst_3hr_window(times, sustained_raw, gusts_raw)
    if ww:
        st.info(
            "Worst 3-hour window: "
            f"{ww['start'].replace('T',' ')} to {ww['end'].replace('T',' ')}. "
            f"Avg sustained {int(round(ww['sustained_avg']))} mph, avg gust {int(round(ww['gust_avg']))} mph."
        )

    st.subheader("Quick notes")
    notes = []
    notes.append("All wind values are in miles per hour (mph).")
    notes.append("Wind and gusts drive the rating. Gusty days can feel much worse than the average wind shows.")
    if offshore:
        notes.append("Offshore wind option enabled: more conservative rating.")
    if big_water:
        notes.append("Big water option enabled: more conservative rating for large lakes or open stretches.")
    st.write(" ".join(notes))

except RuntimeError as e:
    st.error(str(e))
except Exception as e:
    st.error(f"Unexpected error: {e}")