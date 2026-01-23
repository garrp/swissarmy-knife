# app.py
# Kayak Wind Advisor (Streamlit)
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "1.1.0"

# PNW scope (filter reverse-geocode name to these states)
PNW_COUNTRY_CODE = "US"
PNW_ALLOWED_STATES = {"Washington", "Oregon", "Idaho", "Montana"}

FORECAST_TIMEZONE = "America/Los_Angeles"
WIND_UNIT = "mph"  # always mph


# ----------------------------
# Helpers
# ----------------------------
def http_get_json(url: str, params: dict, timeout: int = 20) -> dict:
    try:
        r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "KayakWindAdvisor/1.1.0"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(f"Request failed: {e}")


def safe_float_list(x) -> List[float]:
    if x is None:
        return []
    return [float(v) if v is not None else float("nan") for v in x]


def deg_to_compass(deg: float) -> str:
    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    i = int((deg / 22.5) + 0.5) % 16
    return dirs[i]


def status_color(status: str) -> str:
    if status == "GO":
        return "#1b8f3a"
    if status == "CAUTION":
        return "#c08a00"
    return "#b00020"


def reverse_geocode_name(lat: float, lon: float) -> Optional[str]:
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
        name = (r.get("name") or "").strip()
        country = (r.get("country") or "").strip()
        return f"{name}, {admin1}, {country}"

    # Still show something if outside filter, but label it clearly
    name = (r.get("name") or "").strip()
    admin1 = (r.get("admin1") or "").strip()
    country = (r.get("country") or "").strip()
    if name:
        return f"{name}, {admin1}, {country}"
    return None


def fetch_forecast(lat: float, lon: float) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": FORECAST_TIMEZONE,
        "windspeed_unit": WIND_UNIT,
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "hourly": ",".join(
            [
                "temperature_2m",
                "precipitation_probability",
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
                "wind_speed_10m_max",
                "wind_gusts_10m_max",
                "wind_direction_10m_dominant",
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


def compute_kayak_rating(sustained_mph: float, gust_mph: float) -> str:
    # Simple, no extra options. Assumes typical small water / typical users.
    # GO: sustained 0-10 and gust <= 15
    # CAUTION: sustained 11-15 or gust 16-22
    # DO NOT GO: sustained >= 16 or gust >= 23
    if sustained_mph >= 16 or gust_mph >= 23:
        return "DO NOT GO"
    if sustained_mph >= 11 or gust_mph >= 16:
        return "CAUTION"
    return "GO"


# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Kayak Wind Advisor", layout="centered")

st.title("Kayak Wind Advisor")
st.caption(f"Version {APP_VERSION}. Uses your device location and shows results automatically. Wind is always mph.")

# Small input: date only (optional but useful)
target_day = st.date_input("Choose a date", value=date.today())

# JS geolocation (best effort) - no button required
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

# Pull lat/lon from query params and keep last known in session_state
q = st.query_params
lat = None
lon = None
try:
    if "lat" in q and "lon" in q:
        lat = float(q["lat"])
        lon = float(q["lon"])
        st.session_state["last_lat"] = lat
        st.session_state["last_lon"] = lon
except Exception:
    lat = None
    lon = None

if lat is None or lon is None:
    if "last_lat" in st.session_state and "last_lon" in st.session_state:
        lat = float(st.session_state["last_lat"])
        lon = float(st.session_state["last_lon"])

if lat is None or lon is None:
    st.info("Waiting for your location permission. If nothing happens, enable location for your browser/app and refresh.")
    st.stop()

# Fetch and display
try:
    place_name = reverse_geocode_name(lat, lon) or "Your location"
    forecast = fetch_forecast(lat, lon)
    hourly = forecast.get("hourly") or {}
    daily = forecast.get("daily") or {}

    hourly_day = filter_to_day(hourly, target_day)

    times = hourly_day.get("time") or []
    wind = safe_float_list(hourly_day.get("wind_speed_10m"))
    gust = safe_float_list(hourly_day.get("wind_gusts_10m"))
    wdir = safe_float_list(hourly_day.get("wind_direction_10m"))
    temp = safe_float_list(hourly_day.get("temperature_2m"))
    pop = safe_float_list(hourly_day.get("precipitation_probability"))

    if not times:
        st.warning("No hourly data returned for that date. Try another date.")
        st.stop()

    # Pick a "worst hour" for the day
    rank = {"GO": 0, "CAUTION": 1, "DO NOT GO": 2}
    worst_status = "GO"
    worst_i = 0
    worst_score = -1

    for i in range(len(times)):
        s = wind[i]
        g = gust[i]
        d = wdir[i]
        if s != s or g != g or d != d:
            continue

        r_i = compute_kayak_rating(s, g)
        score = int(round(4.0 * s + 2.0 * max(0.0, g - s)))

        if (rank[r_i] > rank[worst_status]) or (rank[r_i] == rank[worst_status] and score > worst_score):
            worst_status = r_i
            worst_i = i
            worst_score = score

    # Top card
    st.markdown(
        f"""
<div style="border-radius:16px; padding:16px; border:1px solid rgba(0,0,0,0.08);">
  <div style="font-size:14px; opacity:0.8;">{place_name}</div>
  <div style="font-size:34px; font-weight:700; color:{status_color(worst_status)}; margin-top:6px;">{worst_status}</div>
  <div style="font-size:16px; margin-top:6px;">
    Worst hour wind: {int(round(wind[worst_i]))} mph, gusts {int(round(gust[worst_i]))} mph
  </div>
  <div style="font-size:13px; opacity:0.75; margin-top:8px;">
    {times[worst_i].replace("T"," ")} - {deg_to_compass(wdir[worst_i])}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Daily quick stats (if available)
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
        pmax = (daily.get("precipitation_probability_max") or [None])[daily_idx]
        wmax = (daily.get("wind_speed_10m_max") or [None])[daily_idx]
        gmax = (daily.get("wind_gusts_10m_max") or [None])[daily_idx]

        c1.metric("Temp", f"{int(round(tmax))}/{int(round(tmin))} F" if tmax is not None and tmin is not None else "n/a")
        c2.metric("Rain chance", f"{int(pmax)}%" if pmax is not None else "n/a")
        c3.metric("Max wind", f"{int(round(wmax))} mph" if wmax is not None else "n/a")
        c4.metric("Max gust", f"{int(round(gmax))} mph" if gmax is not None else "n/a")

    # Trimmed wind table (next 10 hours)
    st.subheader("Next hours (wind in mph)")
    rows = []
    for i in range(min(10, len(times))):
        s = wind[i]
        g = gust[i]
        d = wdir[i]
        if s != s or g != g or d != d:
            continue
        rows.append(
            {
                "Time": times[i].replace("T", " "),
                "Wind (mph)": int(round(s)),
                "Gust (mph)": int(round(g)),
                "Dir": deg_to_compass(d),
                "Kayak": compute_kayak_rating(s, g),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)

    # Simple chart
    st.subheader("Wind chart (mph)")
    import pandas as pd

    chart_df = pd.DataFrame(
        {
            "time": [t.replace("T", " ") for t in times],
            "wind_mph": wind[: len(times)],
            "gust_mph": gust[: len(times)],
        }
    ).set_index("time")
    st.line_chart(chart_df)

except RuntimeError as e:
    st.error(str(e))
except Exception as e:
    st.error(f"Unexpected error: {e}")