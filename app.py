# app.py
# Kayak Wind Advisor (Streamlit)
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "1.2.1"

FORECAST_TIMEZONE = "America/Los_Angeles"
WIND_UNIT = "mph"


# ----------------------------
# Helpers
# ----------------------------
def http_get_json(url: str, params: dict, timeout: int = 20) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "KayakWindAdvisor/1.2.1"})
    r.raise_for_status()
    return r.json()


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
    try:
        data = http_get_json(
            "https://geocoding-api.open-meteo.com/v1/reverse",
            {"latitude": lat, "longitude": lon, "language": "en", "format": "json"},
        )
        results = data.get("results") or []
        if not results:
            return None
        r = results[0]
        return f"{r.get('name','')}, {r.get('admin1','')}, {r.get('country','')}"
    except:
        return None


def ip_location():
    try:
        data = http_get_json("https://ipapi.co/json/", {})
        return float(data["latitude"]), float(data["longitude"])
    except:
        return None, None


def fetch_forecast(lat: float, lon: float) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": FORECAST_TIMEZONE,
        "windspeed_unit": WIND_UNIT,
        "temperature_unit": "fahrenheit",
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
        if datetime.fromisoformat(t).date() == target:
            idx.append(i)

    for k, v in hourly.items():
        if k == "time":
            out["time"] = [times[i] for i in idx]
        else:
            if isinstance(v, list):
                out[k] = [v[i] for i in idx]
    return out


def compute_kayak_rating(sustained_mph: float, gust_mph: float) -> str:
    if sustained_mph >= 16 or gust_mph >= 23:
        return "DO NOT GO"
    if sustained_mph >= 11 or gust_mph >= 16:
        return "CAUTION"
    return "GO"


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Kayak Wind Advisor", layout="centered")

st.title("Kayak Wind Advisor")
st.caption(f"Version {APP_VERSION}. Uses your location automatically. Wind in mph.")

target_day = st.date_input("Choose a date", value=date.today())

# Always run geolocation JS
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

# Try GPS first
q = st.query_params
lat = None
lon = None
try:
    if "lat" in q and "lon" in q:
        lat = float(q["lat"])
        lon = float(q["lon"])
        st.session_state["last_lat"] = lat
        st.session_state["last_lon"] = lon
except:
    pass

# Fallback to cached
if lat is None and "last_lat" in st.session_state:
    lat = st.session_state["last_lat"]
    lon = st.session_state["last_lon"]

# Final fallback: IP
if lat is None:
    ip_lat, ip_lon = ip_location()
    if ip_lat is not None:
        lat = ip_lat
        lon = ip_lon
        st.session_state["last_lat"] = lat
        st.session_state["last_lon"] = lon

if lat is None:
    st.info("Waiting for location...")
    st.stop()

# Fetch forecast
place_name = reverse_geocode_name(lat, lon) or "Your location"
forecast = fetch_forecast(lat, lon)

hourly = forecast.get("hourly") or {}
daily = forecast.get("daily") or {}

hourly_day = filter_to_day(hourly, target_day)

times = hourly_day.get("time") or []
wind = safe_float_list(hourly_day.get("wind_speed_10m"))
gust = safe_float_list(hourly_day.get("wind_gusts_10m"))
wdir = safe_float_list(hourly_day.get("wind_direction_10m"))

# Find worst hour
rank = {"GO": 0, "CAUTION": 1, "DO NOT GO": 2}
worst_status = "GO"
worst_i = 0
worst_score = -1

for i in range(len(times)):
    s = wind[i]
    g = gust[i]
    r_i = compute_kayak_rating(s, g)
    score = int(round(4.0 * s + 2.0 * max(0.0, g - s)))
    if (rank[r_i] > rank[worst_status]) or (rank[r_i] == rank[worst_status] and score > worst_score):
        worst_status = r_i
        worst_i = i
        worst_score = score

# Top card
st.markdown(
    f"""
<div style="border-radius:16px; padding:16px; border:1px solid rgba(0,0,0,0.1);">
  <div style="font-size:14px; opacity:0.8;">{place_name}</div>
  <div style="font-size:34px; font-weight:700; color:{status_color(worst_status)};">{worst_status}</div>
  <div style="font-size:16px;">
    Worst hour: {int(round(wind[worst_i]))} mph, gusts {int(round(gust[worst_i]))} mph
  </div>
  <div style="font-size:13px; opacity:0.7;">
    {times[worst_i].replace("T"," ")} - {deg_to_compass(wdir[worst_i])}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# Daily summary
daily_time = daily.get("time") or []
daily_idx = daily_time.index(target_day.isoformat()) if target_day.isoformat() in daily_time else None

if daily_idx is not None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Temp", f"{int(daily['temperature_2m_max'][daily_idx])}/{int(daily['temperature_2m_min'][daily_idx])} F")
    c2.metric("Rain chance", f"{daily['precipitation_probability_max'][daily_idx]}%")
    c3.metric("Max wind", f"{int(daily['wind_speed_10m_max'][daily_idx])} mph")
    c4.metric("Max gust", f"{int(daily['wind_gusts_10m_max'][daily_idx])} mph")

# Next hours table (this is now the main detail view)
st.subheader("Next hours (mph)")
rows = []
for i in range(min(10, len(times))):
    rows.append(
        {
            "Time": times[i].replace("T", " "),
            "Wind": int(round(wind[i])),
            "Gust": int(round(gust[i])),
            "Dir": deg_to_compass(wdir[i]),
            "Kayak": compute_kayak_rating(wind[i], gust[i]),
        }
    )
st.dataframe(rows, use_container_width=True, hide_index=True)