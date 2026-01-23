# app.py
# Kayak Compass
# Version 1.0.2
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "1.0.2"

FORECAST_TIMEZONE = "America/Los_Angeles"
WIND_UNIT = "mph"

PAGE_BG_DARK = "#0b0f12"


# ----------------------------
# Helpers
# ----------------------------
def http_get_json(url: str, params: dict, timeout: int = 20) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "KayakCompass/1.0.2"})
    r.raise_for_status()
    return r.json()


def safe_float_list(x) -> List[float]:
    if x is None:
        return []
    return [float(v) if v is not None else float("nan") for v in x]


def deg_to_compass(deg: float) -> str:
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    i = int((deg / 22.5) + 0.5) % 16
    return dirs[i]


def reverse_geocode_name(lat: float, lon: float) -> Optional[str]:
    try:
        data = http_get_json(
            "https://geocoding-api.open-meteo.com/v1/reverse",
            {"latitude": lat, "longitude": lon, "language": "en", "format": "json"},
        )
        r = (data.get("results") or [None])[0]
        if not r:
            return None
        name = (r.get("name") or "").strip()
        admin1 = (r.get("admin1") or "").strip()
        if name and admin1:
            return f"{name}, {admin1}"
        return name or None
    except Exception:
        return None


def ip_location():
    try:
        data = http_get_json("https://ipapi.co/json/", {})
        return float(data["latitude"]), float(data["longitude"])
    except Exception:
        return None, None


def fetch_forecast(lat: float, lon: float) -> dict:
    return http_get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "timezone": FORECAST_TIMEZONE,
            "windspeed_unit": WIND_UNIT,
            "temperature_unit": "fahrenheit",
            "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max",
            "forecast_days": 7,
        },
    )


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


def compute_kayak_rating(sustained_mph: float, gust_mph: float, big_water: bool) -> str:
    # Base thresholds (small water typical)
    go_s = 10
    go_g = 15
    nogo_s = 16
    nogo_g = 23

    # Big water: more conservative
    if big_water:
        go_s = 8
        go_g = 12
        nogo_s = 13
        nogo_g = 19

    if sustained_mph >= nogo_s or gust_mph >= nogo_g:
        return "NO GO"
    if sustained_mph > go_s or gust_mph > go_g:
        return "CAUTION"
    return "GO"


def circle_fill(status: str) -> str:
    if status == "GO":
        return "#2ecc71"
    if status == "CAUTION":
        return "#f1c40f"
    return "#e74c3c"


def stat_grid_html(max_wind_mph: int, max_gust_mph: int, t_hi: int, t_lo: int, rain_pct: int) -> str:
    # Forced 2x2 grid that stays as two columns even on narrow screens.
    # If a screen is extremely tiny, it will still wrap, but on normal phones it will stay 2x2.
    return f"""
<style>
.kc-stats {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin: 10px 0 6px 0;
}}

.kc-card {{
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 14px;
  padding: 12px 12px;
  background: rgba(255,255,255,0.03);
}}

.kc-label {{
  font-size: 13px;
  opacity: 0.80;
  margin-bottom: 6px;
}}

.kc-value {{
  font-size: 32px;
  font-weight: 850;
  line-height: 1.0;
}}

.kc-sub {{
  font-size: 13px;
  opacity: 0.70;
  margin-top: 6px;
}}

@media (max-width: 360px) {{
  .kc-value {{ font-size: 28px; }}
}}
</style>

<div class="kc-stats">
  <div class="kc-card">
    <div class="kc-label">Max wind</div>
    <div class="kc-value">{max_wind_mph} mph</div>
  </div>

  <div class="kc-card">
    <div class="kc-label">Max gust</div>
    <div class="kc-value">{max_gust_mph} mph</div>
  </div>

  <div class="kc-card">
    <div class="kc-label">Temp</div>
    <div class="kc-value">{t_hi}/{t_lo} F</div>
  </div>

  <div class="kc-card">
    <div class="kc-label">Rain</div>
    <div class="kc-value">{rain_pct}%</div>
  </div>
</div>
"""


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Kayak Compass", layout="centered")

st.markdown(
    """
<style>
.block-container {
  padding-top: 44px !important;
  padding-bottom: 16px !important;
}

.kc-title {
  font-size: 30px;
  font-weight: 900;
  line-height: 1.05;
  margin: 0 0 6px 0;
  white-space: nowrap;
  letter-spacing: -1.2px;
  transform: scaleX(0.90);
  font-family: "Trebuchet MS", "Arial Rounded MT Bold", cursive;
}

.kc-circle-wrap {
  width: 100%;
  display: flex;
  justify-content: center;
  margin-top: 10px;
  margin-bottom: 10px;
}
.kc-circle {
  width: min(78vw, 360px);
  height: min(78vw, 360px);
  border-radius: 9999px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 10px 30px rgba(0,0,0,0.22);
}
.kc-circle-text {
  font-size: clamp(46px, 10vw, 92px);
  font-weight: 900;
  letter-spacing: 1px;
  color: """
    + PAGE_BG_DARK
    + """;
  text-transform: uppercase;
}
</style>

<h1 class="kc-title">Kayak Compass</h1>
""",
    unsafe_allow_html=True,
)

st.caption(f"Version {APP_VERSION}. Instant wind-based kayak rating. Wind in mph.")

col_a, col_b = st.columns([2, 1])
with col_a:
    target_day = st.date_input("Choose a date", value=date.today())
with col_b:
    big_water = st.checkbox("Big water", value=False)

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

# GPS first, then cached, then IP fallback
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
    pass

if lat is None and "last_lat" in st.session_state:
    lat = st.session_state["last_lat"]
    lon = st.session_state["last_lon"]

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

place_name = reverse_geocode_name(lat, lon) or "Your location"
forecast = fetch_forecast(lat, lon)

hourly = forecast.get("hourly") or {}
daily = forecast.get("daily") or {}

hourly_day = filter_to_day(hourly, target_day)

times = hourly_day.get("time") or []
wind = safe_float_list(hourly_day.get("wind_speed_10m"))
gust = safe_float_list(hourly_day.get("wind_gusts_10m"))
wdir = safe_float_list(hourly_day.get("wind_direction_10m"))

if not times:
    st.warning("No hourly data returned for that date. Try another date.")
    st.stop()

# Find worst hour
rank = {"GO": 0, "CAUTION": 1, "NO GO": 2}
worst_status = "GO"
worst_i = 0
worst_score = -1

for i in range(len(times)):
    s = wind[i]
    g = gust[i]
    r_i = compute_kayak_rating(s, g, big_water=big_water)
    score = int(round(4.0 * s + 2.0 * max(0.0, g - s)))
    if big_water:
        score += 12

    if (rank[r_i] > rank[worst_status]) or (rank[r_i] == rank[worst_status] and score > worst_score):
        worst_status = r_i
        worst_i = i
        worst_score = score

# Big circle
fill = circle_fill(worst_status)
st.markdown(
    f"""
<div class="kc-circle-wrap">
  <div class="kc-circle" style="background:{fill};">
    <div class="kc-circle-text">{worst_status}</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# Compact details
st.markdown(
    f"""
<div style="margin-top:6px; margin-bottom:6px; font-size:14px; opacity:0.85;">
  {place_name}
</div>
<div style="font-size:16px; margin-bottom:6px;">
  Worst hour: {int(round(wind[worst_i]))} mph wind, {int(round(gust[worst_i]))} mph gusts, {deg_to_compass(wdir[worst_i])}
  <span style="opacity:0.75;">({times[worst_i].replace("T"," ")})</span>
</div>
""",
    unsafe_allow_html=True,
)

# Forced 2x2 daily grid (instead of st.metric, so it does not stack vertically)
daily_time = daily.get("time") or []
if target_day.isoformat() in daily_time:
    d_idx = daily_time.index(target_day.isoformat())

    max_w = int(round(daily["wind_speed_10m_max"][d_idx]))
    max_g = int(round(daily["wind_gusts_10m_max"][d_idx]))
    t_hi = int(round(daily["temperature_2m_max"][d_idx]))
    t_lo = int(round(daily["temperature_2m_min"][d_idx]))
    rain = int(daily["precipitation_probability_max"][d_idx])

    st.markdown(stat_grid_html(max_w, max_g, t_hi, t_lo, rain), unsafe_allow_html=True)

# Next hours table
st.subheader("Next hours (mph)")
rows = []
for i in range(min(10, len(times))):
    rows.append(
        {
            "Time": times[i].replace("T", " "),
            "Wind": int(round(wind[i])),
            "Gust": int(round(gust[i])),
            "Dir": deg_to_compass(wdir[i]),
            "Kayak": compute_kayak_rating(wind[i], gust[i], big_water=big_water),
        }
    )
st.dataframe(rows, use_container_width=True, hide_index=True)