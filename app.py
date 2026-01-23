# app.py
# Kayak Go/No-Go
# Version 1.0.9
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "1.0.9"
OTHER_APP_URL = "https://fishing-tools.streamlit.app/"

FORECAST_TIMEZONE = "America/Los_Angeles"
WIND_UNIT = "mph"
PAGE_BG_DARK = "#0b0f12"


# ----------------------------
# Helpers
# ----------------------------
def http_get_json(url: str, params: dict, timeout: int = 20) -> dict:
    r = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "KayakGoNoGo/1.0.9"})
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


def deg_to_compass(deg: float) -> str:
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    i = int((deg / 22.5) + 0.5) % 16
    return dirs[i]


def compute_wind_rating(s: float, g: float, big_water: bool) -> str:
    # Small water typical
    if not big_water:
        if s >= 16 or g >= 23:
            return "NO GO"
        if s > 10 or g > 15:
            return "CAUTION"
        return "GO"

    # Big water (more conservative)
    if s >= 13 or g >= 19:
        return "NO GO"
    if s > 8 or g > 12:
        return "CAUTION"
    return "GO"


def exposure_risk_level(temp_hi_f: int, temp_lo_f: int, max_wind_mph: int, big_water: bool) -> str:
    # LOW, MODERATE, HIGH
    risk = "LOW"

    # Air temp buckets (PNW)
    if temp_lo_f <= 28 or temp_hi_f <= 36:
        risk = "HIGH"
    elif temp_lo_f <= 38 or temp_hi_f <= 48:
        risk = "MODERATE"

    # Wind bump
    if max_wind_mph >= 15 and risk == "LOW":
        risk = "MODERATE"
    elif max_wind_mph >= 15 and risk == "MODERATE":
        risk = "HIGH"

    # Big water bump
    if big_water and risk == "LOW":
        risk = "MODERATE"
    elif big_water and risk == "MODERATE":
        risk = "HIGH"

    return risk


def combine_ratings(wind_status: str, exposure_risk: str) -> str:
    # Wind NO GO always wins.
    if wind_status == "NO GO":
        return "NO GO"

    # High exposure forces at least CAUTION.
    if exposure_risk == "HIGH":
        return "CAUTION"

    return wind_status


def circle_fill(status: str) -> str:
    return {"GO": "#2ecc71", "CAUTION": "#f1c40f", "NO GO": "#e74c3c"}[status]


def exposure_advice(exposure_risk: str) -> List[str]:
    if exposure_risk == "LOW":
        return [
            "Exposure looks manageable, but stay dry and keep a wind layer handy.",
            "Dry bag with a spare layer is smart in the PNW.",
            "PFD worn, whistle, phone in a waterproof case.",
        ]

    if exposure_risk == "MODERATE":
        return [
            "Cool/cold exposure risk. Dress for wind and the chance of getting wet.",
            "Recommended: waterproof/windproof outer layer, insulating mid-layer, warm hat and gloves.",
            "Dry bag: spare clothes. PFD worn, whistle, phone in a waterproof case.",
        ]

    return [
        "High cold exposure risk. If you get wet, the margin for error shrinks fast.",
        "Strongly consider: drysuit (best) or appropriate wetsuit, insulating layers (avoid cotton), warm hat and gloves.",
        "Dry bag: full spare set plus towel. PFD worn, whistle, phone in a waterproof case.",
    ]


# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Kayak Go/No-Go", layout="centered")

st.markdown(
    """
<style>
.block-container { padding-top: 44px !important; padding-bottom: 16px !important; }

.kc-title {
  font-size: 30px;
  font-weight: 900;
  letter-spacing: -1.2px;
  transform: scaleX(0.90);
  font-family: "Trebuchet MS", "Arial Rounded MT Bold", cursive;
  white-space: nowrap;
  margin: 0 0 6px 0;
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

/* Sidebar polish (nav only) */
section[data-testid="stSidebar"] {
  border-right: 1px solid rgba(255,255,255,0.08);
}
</style>

<h1 class="kc-title">Kayak Go/No-Go</h1>
""",
    unsafe_allow_html=True,
)

st.caption(f"Kayak Go/No-Go | Version {APP_VERSION}. Wind and exposure based rating. Wind in mph.")

# Sidebar (NAV ONLY)
with st.sidebar:
    st.subheader("Navigation")
    st.link_button("Fishing Tools", OTHER_APP_URL)
    st.caption("Opens in a new tab.")

# Main controls
col_a, col_b = st.columns([2, 1])
with col_a:
    target_day = st.date_input("Choose a date", value=date.today())
with col_b:
    big_water = st.checkbox("Big water", value=False)

# Location JS (always runs)
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

# GPS -> cached -> IP fallback
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

# Worst hour based on wind+gust
worst_i = max(range(len(times)), key=lambda i: float(wind[i]) + float(gust[i]))
wind_status = compute_wind_rating(float(wind[worst_i]), float(gust[worst_i]), big_water)

# Daily values for summary + exposure
daily_time = daily.get("time") or []
t_hi = None
t_lo = None
max_w = None
max_g = None
rain = None

if target_day.isoformat() in daily_time:
    d_idx = daily_time.index(target_day.isoformat())
    max_w = int(round(daily["wind_speed_10m_max"][d_idx]))
    max_g = int(round(daily["wind_gusts_10m_max"][d_idx]))
    t_hi = int(round(daily["temperature_2m_max"][d_idx]))
    t_lo = int(round(daily["temperature_2m_min"][d_idx]))
    rain = int(daily["precipitation_probability_max"][d_idx])

exposure_risk = "LOW"
if t_hi is not None and t_lo is not None and max_w is not None:
    exposure_risk = exposure_risk_level(t_hi, t_lo, max_w, big_water)

status = combine_ratings(wind_status, exposure_risk)

# Big circle
st.markdown(
    f"""
<div class="kc-circle-wrap">
  <div class="kc-circle" style="background:{circle_fill(status)};">
    <div class="kc-circle-text">{status}</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# Compact details
worst_dir = ""
if len(wdir) > worst_i:
    worst_dir = deg_to_compass(float(wdir[worst_i]))

st.markdown(
    f"""
<div style="margin-top:6px; margin-bottom:6px; font-size:14px; opacity:0.85;">
  {place_name}
</div>
<div style="font-size:16px; margin-bottom:6px;">
  Worst hour: {int(round(wind[worst_i]))} mph wind, {int(round(gust[worst_i]))} mph gusts {worst_dir}
  <span style="opacity:0.75;">({times[worst_i].replace("T"," ")})</span>
</div>
""",
    unsafe_allow_html=True,
)

if wind_status == "GO" and status == "CAUTION" and exposure_risk == "HIGH":
    st.info("Caution due to cold exposure risk. Wind looks OK, but getting wet in these temps can be dangerous.")

# ---- WIND HOURS TABLE (ABOVE EXPOSURE) ----
st.subheader("Next hours (mph)")
rows = []
for i in range(min(10, len(times))):
    rows.append(
        {
            "Time": times[i].replace("T", " "),
            "Wind": int(round(wind[i])),
            "Gust": int(round(gust[i])),
            "Dir": deg_to_compass(float(wdir[i])) if i < len(wdir) else "",
            "Rating": compute_wind_rating(float(wind[i]), float(gust[i]), big_water),
        }
    )
st.dataframe(rows, use_container_width=True, hide_index=True)

# Daily forced 2x2 table
if (max_w is not None) and (max_g is not None) and (t_hi is not None) and (t_lo is not None) and (rain is not None):
    st.markdown(
        f"""
<table style="width:100%; text-align:center; margin-top:10px; border-collapse:separate; border-spacing:10px;">
  <tr>
    <td style="border:1px solid rgba(255,255,255,0.10); border-radius:14px; padding:12px; background:rgba(255,255,255,0.03);">
      <div style="font-size:13px; opacity:0.80;">Max wind</div>
      <div style="font-size:32px; font-weight:850; line-height:1.0;">{max_w} mph</div>
    </td>
    <td style="border:1px solid rgba(255,255,255,0.10); border-radius:14px; padding:12px; background:rgba(255,255,255,0.03);">
      <div style="font-size:13px; opacity:0.80;">Max gust</div>
      <div style="font-size:32px; font-weight:850; line-height:1.0;">{max_g} mph</div>
    </td>
  </tr>
  <tr>
    <td style="border:1px solid rgba(255,255,255,0.10); border-radius:14px; padding:12px; background:rgba(255,255,255,0.03);">
      <div style="font-size:13px; opacity:0.80;">Temp</div>
      <div style="font-size:32px; font-weight:850; line-height:1.0;">{t_hi}/{t_lo} F</div>
    </td>
    <td style="border:1px solid rgba(255,255,255,0.10); border-radius:14px; padding:12px; background:rgba(255,255,255,0.03);">
      <div style="font-size:13px; opacity:0.80;">Rain</div>
      <div style="font-size:32px; font-weight:850; line-height:1.0;">{rain}%</div>
    </td>
  </tr>
</table>
""",
        unsafe_allow_html=True,
    )

    # ---- EXPOSURE SECTION (BELOW TABLE) ----
    st.markdown(f"### Exposure - {exposure_risk}")
    for line in exposure_advice(exposure_risk):
        st.write(line)