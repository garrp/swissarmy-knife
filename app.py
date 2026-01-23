# app.py
# Kayak Compass
# Version 1.0.8
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "1.0.8"
OTHER_APP_URL = "https://fishing-tools.streamlit.app/"

FORECAST_TIMEZONE = "America/Los_Angeles"
WIND_UNIT = "mph"
PAGE_BG_DARK = "#0b0f12"


# ----------------------------
# Helpers
# ----------------------------
def http_get_json(url: str, params: dict, timeout: int = 20) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "KayakCompass/1.0.8"})
    r.raise_for_status()
    return r.json()


def safe_float_list(x) -> List[float]:
    if x is None:
        return []
    return [float(v) if v is not None else float("nan") for v in x]


def reverse_geocode_name(lat: float, lon: float) -> Optional[str]:
    try:
        data = http_get_json(
            "https://geocoding-api.open-meteo.com/v1/reverse",
            {"latitude": lat, "longitude": lon, "language": "en", "format": "json"},
        )
        r = (data.get("results") or [None])[0]
        if not r:
            return None
        return f"{r.get('name','')}, {r.get('admin1','')}"
    except:
        return None


def ip_location():
    try:
        data = http_get_json("https://ipapi.co/json/", {})
        return float(data["latitude"]), float(data["longitude"])
    except:
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
            "hourly": "wind_speed_10m,wind_gusts_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max",
            "forecast_days": 7,
        },
    )


def filter_to_day(hourly: dict, target: date) -> dict:
    times = hourly["time"]
    idx = [i for i,t in enumerate(times) if datetime.fromisoformat(t).date() == target]
    return {k: [v[i] for i in idx] if isinstance(v,list) else v for k,v in hourly.items()}


def compute_wind_rating(s: float, g: float, big_water: bool) -> str:
    if not big_water:
        if s >= 16 or g >= 23: return "NO GO"
        if s > 10 or g > 15: return "CAUTION"
    else:
        if s >= 13 or g >= 19: return "NO GO"
        if s > 8 or g > 12: return "CAUTION"
    return "GO"


def exposure_risk(temp_hi, temp_lo, max_wind, big_water):
    risk = "LOW"
    if temp_lo <= 28 or temp_hi <= 36:
        risk = "HIGH"
    elif temp_lo <= 38 or temp_hi <= 48:
        risk = "MODERATE"
    if max_wind >= 15 and risk == "LOW":
        risk = "MODERATE"
    if big_water and risk == "LOW":
        risk = "MODERATE"
    return risk


def combine_ratings(wind_status, exposure):
    if wind_status == "NO GO":
        return "NO GO"
    if exposure == "HIGH":
        return "CAUTION"
    return wind_status


def circle_fill(status):
    return {"GO":"#2ecc71","CAUTION":"#f1c40f","NO GO":"#e74c3c"}[status]


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Kayak Compass", layout="centered")

st.markdown("""
<style>
.block-container { padding-top: 44px !important; }
.kc-title {
  font-size: 30px;
  font-weight: 900;
  transform: scaleX(0.9);
  font-family: "Trebuchet MS", cursive;
}
.kc-circle {
  width: min(78vw, 360px);
  height: min(78vw, 360px);
  border-radius: 9999px;
  display:flex;
  align-items:center;
  justify-content:center;
}
.kc-circle-text {
  font-size: clamp(46px, 10vw, 92px);
  font-weight: 900;
  color: """+PAGE_BG_DARK+""";
}
</style>
<h1 class="kc-title">Kayak Compass</h1>
""", unsafe_allow_html=True)

st.caption(f"Version {APP_VERSION}")

with st.sidebar:
    st.link_button("Fishing Tools", OTHER_APP_URL)

col_a, col_b = st.columns([2,1])
with col_a:
    target_day = st.date_input("Choose a date", value=date.today())
with col_b:
    big_water = st.checkbox("Big water", value=False)

components.html("""
<script>
navigator.geolocation?.getCurrentPosition(pos=>{
  const u=new URL(window.location);
  u.searchParams.set("lat",pos.coords.latitude);
  u.searchParams.set("lon",pos.coords.longitude);
  history.replaceState({},'',u);
});
</script>
""", height=0)

lat = st.query_params.get("lat")
lon = st.query_params.get("lon")
if not lat:
    lat,lon = ip_location()
else:
    lat,lon = float(lat), float(lon)

data = fetch_forecast(lat,lon)
hourly = filter_to_day(data["hourly"], target_day)
daily = data["daily"]

wind = safe_float_list(hourly["wind_speed_10m"])
gust = safe_float_list(hourly["wind_gusts_10m"])
times = hourly["time"]

worst_i = max(range(len(times)), key=lambda i: wind[i]+gust[i])
wind_status = compute_wind_rating(wind[worst_i], gust[worst_i], big_water)

d_idx = daily["time"].index(target_day.isoformat())
t_hi = int(daily["temperature_2m_max"][d_idx])
t_lo = int(daily["temperature_2m_min"][d_idx])
max_w = int(daily["wind_speed_10m_max"][d_idx])
rain = int(daily["precipitation_probability_max"][d_idx])

exposure = exposure_risk(t_hi, t_lo, max_w, big_water)
status = combine_ratings(wind_status, exposure)

st.markdown(f"""
<div style="display:flex;justify-content:center;margin:12px 0;">
  <div class="kc-circle" style="background:{circle_fill(status)};">
    <div class="kc-circle-text">{status}</div>
  </div>
</div>
""", unsafe_allow_html=True)

# ---- WIND HOURS TABLE (NOW ABOVE EXPOSURE) ----
st.subheader("Next hours (mph)")
rows=[]
for i in range(min(10,len(times))):
    rows.append({
        "Time": times[i].replace("T"," "),
        "Wind": int(wind[i]),
        "Gust": int(gust[i]),
        "Rating": compute_wind_rating(wind[i],gust[i],big_water)
    })
st.dataframe(rows, use_container_width=True, hide_index=True)

# ---- DAILY SUMMARY ----
st.markdown(f"""
**Daily:** {t_hi}/{t_lo} F | Max wind {max_w} mph | Rain {rain}%
""")

# ---- EXPOSURE SECTION (NOW BELOW TABLE) ----
st.markdown(f"### Exposure - {exposure}")

if exposure == "LOW":
    st.write("Exposure looks manageable. Bring a wind layer and stay dry.")
elif exposure == "MODERATE":
    st.write("Cold exposure possible. Dress for wind and water. Bring insulating layers.")
else:
    st.write("High cold exposure risk. Strongly consider a drysuit or staying off the water.")
    st.write("Full spare clothes in dry bag, warm hat and gloves, PFD worn.")