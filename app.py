# app.py
# Kayak Wind Advisor (Streamlit)
# ASCII ONLY. No Unicode. No smart quotes. No special dashes.

from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import List, Optional, Tuple

import requests
import streamlit as st


APP_VERSION = "1.0.1"

# Pacific Northwest scope (edit if you want to expand)
PNW_COUNTRY_CODE = "US"
PNW_ALLOWED_STATES = {"Washington", "Oregon", "Idaho", "Montana"}
FORECAST_TIMEZONE = "America/Los_Angeles"


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


def mph_from(value: float, unit: str) -> float:
    # Open-Meteo supports windspeed_unit: mph, ms, kmh, kn
    if unit == "mph":
        return float(value)
    if unit == "kmh":
        return float(value) * 0.621371
    if unit == "ms":
        return float(value) * 2.23694
    if unit == "kn":
        return float(value) * 1.15078
    return float(value)


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


def worst_window(times: List[str], sustained_mph: List[float], gusts_mph: List[float]) -> Optional[dict]:
    # Find worst 3-hour window by average wind score
    if not times or not sustained_mph or not gusts_mph:
        return None

    n = min(len(times), len(sustained_mph), len(gusts_mph))
    if n < 3:
        return None

    scores = []
    for i in range(n):
        s = sustained_mph[i]
        g = gusts_mph[i]
        if s != s or g != g:
            scores.append(None)
        else:
            gustiness = max(0.0, g - s)
            scores.append(4.0 * s + 2.0 * gustiness)

    best = None
    for i in range(0, n - 2):
        window = scores[i : i + 3]
        if any(v is None for v in window):
            continue
        avg = sum(window) / 3.0
        if (best is None) or (avg > best["avg_score"]):
            best = {
                "start": times[i],
                "end": times[i + 2],
                "avg_score": avg,
                "sustained_avg": sum(sustained_mph[i : i + 3]) / 3.0,
                "gust_avg": sum(gusts_mph[i : i + 3]) / 3.0,
            }
    return best


def geocode_place_pnw(place: str) -> List[dict]:
    """
    Uses Open-Meteo geocoding and filters to PNW states only.
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": place, "count": 12, "language": "en", "format": "json"}
    data = http_get_json(url, params=params)
    results = data.get("results") or []

    filtered = []
    for r in results:
        country_code = (r.get("country_code") or "").strip()
        admin1 = (r.get("admin1") or "").strip()
        # Keep only US PNW state results
        if country_code == PNW_COUNTRY_CODE and admin1 in PNW_ALLOWED_STATES:
            filtered.append(r)

    return filtered


def fetch_forecast(lat: float, lon: float, wind_unit: str) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": FORECAST_TIMEZONE,
        "windspeed_unit": wind_unit,  # mph, kn, kmh, ms
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
        "forecast_days": 3,
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


def pick_day_label(target: date) -> str:
    today = date.today()
    if target == today:
        return "Today"
    if target == today + timedelta(days=1):
        return "Tomorrow"
    return target.isoformat()


def status_color(status: str) -> str:
    if status == "GO":
        return "#1b8f3a"
    if status == "CAUTION":
        return "#c08a00"
    return "#b00020"


# ----------------------------
# Streamlit UI
# ----------------------------
st.set_page_config(page_title="Kayak Wind Advisor", layout="centered")

st.title("Kayak Wind Advisor")
st.caption(
    f"Version {APP_VERSION}. Pacific Northwest only (WA, OR, ID, MT). Wind-first GO / CAUTION / DO NOT GO."
)

with st.sidebar:
    st.subheader("Location (PNW only)")
    place = st.text_input("Place name (city, lake, launch)", value="Coeur d'Alene")

    st.subheader("Day")
    day_choice = st.radio("Pick a day", ["Today", "Tomorrow", "Pick a date"], index=0)
    if day_choice == "Pick a date":
        target_day = st.date_input("Date", value=date.today())
    elif day_choice == "Tomorrow":
        target_day = date.today() + timedelta(days=1)
    else:
        target_day = date.today()

    st.subheader("Wind settings")
    wind_unit = st.selectbox("Wind units", ["mph", "kn"], index=0)

    offshore = st.checkbox("Assume offshore wind risk", value=False)
    big_water = st.checkbox("Big water (large lake, long fetch)", value=True)

    st.subheader("Decision style")
    st.caption("Conservative defaults for most recreational kayak anglers.")
    go_max = st.slider("GO sustained max", min_value=5, max_value=15, value=10, step=1)
    caution_max = st.slider("CAUTION sustained max", min_value=10, max_value=25, value=15, step=1)
    go_gust_max = st.slider("GO gust max", min_value=10, max_value=25, value=15, step=1)
    caution_gust_max = st.slider("CAUTION gust max", min_value=15, max_value=35, value=22, step=1)

st.caption(f"Forecast timezone locked to {FORECAST_TIMEZONE} (PNW local display).")


def compute_status_custom(sustained_mph: float, gust_mph: float) -> str:
    if sustained_mph >= (caution_max + 1) or gust_mph >= (caution_gust_max + 1):
        return "DO NOT GO"
    if sustained_mph > go_max or gust_mph > go_gust_max:
        return "CAUTION"
    return "GO"


def apply_bump(status: str, offshore_flag: bool, big_water_flag: bool) -> str:
    if status == "DO NOT GO":
        return status
    if offshore_flag or big_water_flag:
        if status == "GO":
            return "CAUTION"
        if status == "CAUTION":
            return "DO NOT GO"
    return status


# ----------------------------
# Run
# ----------------------------
if not place.strip():
    st.info("Enter a PNW place name to get a wind-first kayak rating.")
    st.stop()

try:
    results = geocode_place_pnw(place.strip())
    if not results:
        allowed = ", ".join(sorted(list(PNW_ALLOWED_STATES)))
        st.error(
            "No PNW matches found. Try a nearby town name.\n\n"
            f"Allowed area: {PNW_COUNTRY_CODE} only, states: {allowed}."
        )
        st.stop()

    label_options = []
    for r in results:
        name = r.get("name", "")
        admin1 = r.get("admin1", "")
        country = r.get("country", "")
        lat = r.get("latitude", 0.0)
        lon = r.get("longitude", 0.0)
        label_options.append(f"{name}, {admin1}, {country} ({lat:.3f}, {lon:.3f})")

    chosen = st.selectbox("Select the best match", label_options, index=0)
    chosen_idx = label_options.index(chosen)
    chosen_r = results[chosen_idx]

    lat = float(chosen_r["latitude"])
    lon = float(chosen_r["longitude"])

    forecast = fetch_forecast(lat, lon, wind_unit=wind_unit)
    hourly = forecast.get("hourly") or {}
    daily = forecast.get("daily") or {}

    hourly_day = filter_to_day(hourly, target_day)

    times = hourly_day.get("time") or []
    sustained_raw = safe_float_list(hourly_day.get("wind_speed_10m"))
    gusts_raw = safe_float_list(hourly_day.get("wind_gusts_10m"))
    dirs_raw = safe_float_list(hourly_day.get("wind_direction_10m"))

    sustained_mph = [mph_from(v, wind_unit) for v in sustained_raw]
    gusts_mph = [mph_from(v, wind_unit) for v in gusts_raw]

    if not times:
        st.warning("No hourly data returned for that day. Try another day or location.")
        st.stop()

    # Day-level status: worst hour (conservative)
    worst_status = "GO"
    worst_reason = ""
    worst_score = -1
    worst_i = 0

    rank_map = {"GO": 0, "CAUTION": 1, "DO NOT GO": 2}

    for i in range(len(times)):
        s = sustained_mph[i]
        g = gusts_mph[i]
        d = dirs_raw[i]
        if s != s or g != g or d != d:
            continue

        base = compute_status_custom(s, g)
        bumped = apply_bump(base, offshore, big_water)

        gustiness = max(0.0, g - s)
        score = int(round(4.0 * s + 2.0 * gustiness))
        if offshore:
            score += 10
        if big_water:
            score += 8

        if (rank_map[bumped] > rank_map[worst_status]) or (
            rank_map[bumped] == rank_map[worst_status] and score > worst_score
        ):
            worst_status = bumped
            worst_score = score
            worst_i = i

            worst_reason = f"Sustained {int(round(s))} mph, gusts {int(round(g))} mph."
            if offshore or big_water:
                reasons = []
                if offshore:
                    reasons.append("offshore wind")
                if big_water:
                    reasons.append("big water")
                worst_reason += " Risk higher due to " + ", ".join(reasons) + "."

    day_label = pick_day_label(target_day)

    st.markdown(
        f"""
<div style="border-radius:16px; padding:16px; border:1px solid rgba(0,0,0,0.08);">
  <div style="font-size:14px; opacity:0.8;">{day_label} at {chosen.split(' (')[0]}</div>
  <div style="font-size:34px; font-weight:700; color:{status_color(worst_status)}; margin-top:6px;">{worst_status}</div>
  <div style="font-size:16px; margin-top:6px;">{worst_reason}</div>
  <div style="font-size:13px; opacity:0.75; margin-top:8px;">
    Worst hour: {times[worst_i].replace("T", " ")} ({deg_to_compass(dirs_raw[worst_i])}).
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Daily summary
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
        c3.metric("Max wind", f"{int(round(wmax))} {wind_unit}" if wmax is not None else "n/a")
        if gmax is not None and wdir is not None:
            c4.metric("Max gust", f"{int(round(gmax))} {wind_unit} ({deg_to_compass(float(wdir))})")
        else:
            c4.metric("Max gust", "n/a")

        if sunrise and sunset:
            st.caption(f"Sunrise {sunrise.replace('T',' ')} | Sunset {sunset.replace('T',' ')} (local time)")
    else:
        c1.metric("Temp", "n/a")
        c2.metric("Precip", "n/a")
        c3.metric("Max wind", "n/a")
        c4.metric("Max gust", "n/a")

    st.subheader("Wind focus (hourly)")
    rows = []
    for i in range(len(times)):
        s_mph = sustained_mph[i]
        g_mph = gusts_mph[i]
        d = dirs_raw[i]
        if s_mph != s_mph or g_mph != g_mph or d != d:
            continue

        base = compute_status_custom(s_mph, g_mph)
        bumped = apply_bump(base, offshore, big_water)

        rows.append(
            {
                "Time": times[i].replace("T", " "),
                "Wind": f"{int(round(sustained_raw[i]))} {wind_unit}",
                "Gust": f"{int(round(gusts_raw[i]))} {wind_unit}",
                "Dir": f"{deg_to_compass(d)} ({int(round(d))} deg)",
                "Rating": bumped,
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Wind chart")
    import pandas as pd

    chart_df = pd.DataFrame(
        {
            "time": [t.replace("T", " ") for t in times],
            "wind_speed": sustained_raw[: len(times)],
            "wind_gusts": gusts_raw[: len(times)],
        }
    ).set_index("time")
    st.line_chart(chart_df)

    ww = worst_window(times, sustained_mph, gusts_mph)
    if ww:
        st.info(
            "Worst 3-hour window: "
            f"{ww['start'].replace('T',' ')} to {ww['end'].replace('T',' ')}. "
            f"Avg sustained {int(round(ww['sustained_avg']))} mph, avg gust {int(round(ww['gust_avg']))} mph."
        )

    st.subheader("Quick notes")
    notes = []
    if offshore:
        notes.append("Offshore wind can push you away from shore and make return harder.")
    if big_water:
        notes.append("Big water can build waves fast and reduce safe bailout options.")
    notes.append("Gusts matter. A steady 10 can feel fine, but gusting 20 can turn it into work fast.")
    st.write(" ".join(notes))

except RuntimeError as e:
    st.error(str(e))
except Exception as e:
    st.error(f"Unexpected error: {e}")