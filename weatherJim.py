# #!/usr/bin/env python3


# WEATHER CONSENSUS BOT — Telegram

Fetches high-temperature forecasts from 40+ independent
meteorological data points (10 deterministic models +
31-member GFS ensemble) via Open-Meteo (free, no API key).

SETUP:

1. Install dependencies:
pip install python-telegram-bot httpx
1. Create your bot:
- Open Telegram, search for @BotFather
- Send /newbot, follow the prompts
- Copy the token you receive
1. Paste your token into BOT_TOKEN below (or set env var):
export TELEGRAM_BOT_TOKEN=8589504469:AAFliWw3euwsZdP8zC24KQ0Qs1mEqB7KP34
1. Run:
python weather_consensus_bot.py

# USAGE IN TELEGRAM:
/weather New York City
/weather London, UK
/weather Tokyo
/weather Miami, FL
/start  shows help



import os
import asyncio
import logging
from datetime import date, datetime
from collections import Counter
import statistics
import httpx
from telegram import Update
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
filters,
ContextTypes,
)

# ─── CONFIGURATION ────────────────────────────────────────────

BOT_TOKEN = os.getenv(“TELEGRAM_BOT_TOKEN”, “PASTE_YOUR_BOT_TOKEN_HERE”)

# ─── LOGGING ──────────────────────────────────────────────────

logging.basicConfig(
format=”%(asctime)s | %(levelname)s | %(message)s”,
level=logging.INFO,
)
logger = logging.getLogger(**name**)

# ─── WEATHER MODELS ───────────────────────────────────────────

# All 10 deterministic models queried from Open-Meteo (free, no key)

DETERMINISTIC_MODELS = [
{“model”: “ecmwf_ifs025”, “label”: “ECMWF IFS 0.25° (Europe)”},
{“model”: “gfs_seamless”, “label”: “NOAA GFS (USA)”},
{“model”: “icon_seamless”, “label”: “DWD ICON (Germany)”},
{“model”: “meteofrance_seamless”, “label”: “Météo-France ARPEGE (France)”},
{“model”: “gem_seamless”, “label”: “CMC GEM (Canada)”},
{“model”: “bom_access_global”, “label”: “BOM ACCESS-G (Australia)”},
{“model”: “ukmo_seamless”, “label”: “UK Met Office (UK)”},
{“model”: “jma_seamless”, “label”: “JMA (Japan)”},
{“model”: “cma_grapes_global”, “label”: “CMA GRAPES (China)”},
{“model”: “arpae_cosmo_seamless”, “label”: “ARPAE COSMO (Italy)”},
]

OPEN_METEO_URL = “https://api.open-meteo.com/v1/forecast”
OPEN_METEO_GEO_URL = “https://geocoding-api.open-meteo.com/v1/search”

TIMEOUT = 30.0 # seconds per HTTP request

# ─── GEOCODING ────────────────────────────────────────────────

async def geocode_location(location: str) -> dict | None:
“”“Convert a location string to lat/lon using Open-Meteo Geocoding API.”””
params = {“name”: location, “count”: 1, “language”: “en”, “format”: “json”}
async with httpx.AsyncClient(timeout=TIMEOUT) as client:
try:
resp = await client.get(OPEN_METEO_GEO_URL, params=params)
resp.raise_for_status()
data = resp.json()
results = data.get(“results”)
if results:
r = results[0]
parts = [r.get(“name”, “”)]
if r.get(“admin1”):
parts.append(r[“admin1”])
if r.get(“country”):
parts.append(r[“country”])
return {
“lat”: r[“latitude”],
“lon”: r[“longitude”],
“display”: “, “.join(filter(None, parts)),
“timezone”: r.get(“timezone”, “UTC”),
}
except Exception as e:
logger.warning(f”Geocode error for ‘{location}’: {e}”)
return None

# ─── WEATHER FETCHING ─────────────────────────────────────────

async def fetch_deterministic_model(
client: httpx.AsyncClient, lat: float, lon: float, model: str
) -> float | None:
“”“Fetch today’s max temperature from a single deterministic model.”””
params = {
“latitude”: lat,
“longitude”: lon,
“daily”: “temperature_2m_max”,
“models”: model,
“forecast_days”: 1,
“timezone”: “auto”,
}
try:
resp = await client.get(OPEN_METEO_URL, params=params)
resp.raise_for_status()
data = resp.json()
daily = data.get(“daily”, {})
temps = daily.get(“temperature_2m_max”, [])
if temps and temps[0] is not None:
return float(temps[0])
except Exception as e:
logger.debug(f”Model {model} error: {e}”)
return None

async def fetch_gfs_ensemble(
client: httpx.AsyncClient, lat: float, lon: float
) -> list[float]:
“”“Fetch GFS ensemble — returns up to 31 individual member max temps.”””
params = {
“latitude”: lat,
“longitude”: lon,
“daily”: “temperature_2m_max”,
“models”: “gfs_seamless”,
“ensemble”: “true”,
“forecast_days”: 1,
“timezone”: “auto”,
}
members = []
try:
resp = await client.get(OPEN_METEO_URL, params=params)
resp.raise_for_status()
data = resp.json()
daily = data.get(“daily”, {})
for key, vals in daily.items():
if “temperature_2m_max” in key and vals and vals[0] is not None:
members.append(float(vals[0]))
except Exception as e:
logger.debug(f”GFS ensemble error: {e}”)
return members

async def fetch_ecmwf_ensemble(
client: httpx.AsyncClient, lat: float, lon: float
) -> list[float]:
“”“Fetch ECMWF ensemble — returns individual member max temps if available.”””
params = {
“latitude”: lat,
“longitude”: lon,
“daily”: “temperature_2m_max”,
“models”: “ecmwf_ifs_ensemble”,
“ensemble”: “true”,
“forecast_days”: 1,
“timezone”: “auto”,
}
members = []
try:
resp = await client.get(OPEN_METEO_URL, params=params)
resp.raise_for_status()
data = resp.json()
daily = data.get(“daily”, {})
for key, vals in daily.items():
if “temperature_2m_max” in key and vals and vals[0] is not None:
members.append(float(vals[0]))
except Exception as e:
logger.debug(f”ECMWF ensemble error: {e}”)
return members

async def gather_all_forecasts(lat: float, lon: float) -> dict:
“”“Concurrently collect all deterministic + ensemble data points.”””
async with httpx.AsyncClient(timeout=TIMEOUT) as client:
# Fire off all requests concurrently
det_tasks = [
fetch_deterministic_model(client, lat, lon, m[“model”])
for m in DETERMINISTIC_MODELS
]
ens_gfs_task = fetch_gfs_ensemble(client, lat, lon)
ens_ecmwf_task = fetch_ecmwf_ensemble(client, lat, lon)

```
det_results, gfs_members, ecmwf_members = await asyncio.gather(
asyncio.gather(*det_tasks),
ens_gfs_task,
ens_ecmwf_task,
)

# Pair labels with deterministic results
deterministic = {}
for i, val in enumerate(det_results):
if val is not None:
deterministic[DETERMINISTIC_MODELS[i]["label"]] = val

return {
"deterministic": deterministic,
"gfs_ensemble": gfs_members,
"ecmwf_ensemble": ecmwf_members,
}
```

# ─── ANALYSIS & FORMATTING ────────────────────────────────────

def celsius_to_f(c: float) -> float:
return c * 9 / 5 + 32

def build_report(location_display: str, forecast_data: dict) -> str:
“”“Build the full consensus report message.”””
det = forecast_data[“deterministic”]
gfs = forecast_data[“gfs_ensemble”]
ecmwf = forecast_data[“ecmwf_ensemble”]

```
# Collect all data points
all_temps_c: list[float] = list(det.values()) + gfs + ecmwf
n_total = len(all_temps_c)

if n_total == 0:
return (
"⚠️ Sorry, I couldn't retrieve forecast data for that location.\n"
"Please try again or rephrase the location name."
)

# Statistics
t_mean = statistics.mean(all_temps_c)
t_med = statistics.median(all_temps_c)
t_min = min(all_temps_c)
t_max = max(all_temps_c)
t_stdev = statistics.stdev(all_temps_c) if n_total > 1 else 0.0

# Confidence tier based on spread
if t_stdev < 1.5:
confidence_label = "🟢 Very High"
confidence_note = "(models in strong agreement)"
elif t_stdev < 3.0:
confidence_label = "🟡 High"
confidence_note = "(minor spread between models)"
elif t_stdev < 5.0:
confidence_label = "🟠 Moderate"
confidence_note = "(noticeable spread — check closer to the day)"
else:
confidence_label = "🔴 Low"
confidence_note = "(high uncertainty — large model disagreement)"

# Build temperature distribution bands (1°C wide)
band_floor = int(t_min) - 1
band_ceil = int(t_max) + 2
bands: dict[int, list] = {}
for t in all_temps_c:
bucket = int(t) # floor to 1°C band
bands.setdefault(bucket, []).append(t)

sorted_buckets = sorted(bands.keys())
max_count = max(len(v) for v in bands.values())

today_str = date.today().strftime("%A, %B %-d, %Y")

lines = []
lines.append(f"📍 *{location_display}*")
lines.append(f"📅 {today_str}")
lines.append(f"")
lines.append(f"🌡 *HIGH TEMPERATURE CONSENSUS*")
lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
lines.append(f"📊 Data points analyzed: *{n_total}*")
lines.append(f" • Deterministic models: {len(det)}/10")
if gfs:
lines.append(f" • GFS ensemble members: {len(gfs)}")
if ecmwf:
lines.append(f" • ECMWF ensemble members: {len(ecmwf)}")
lines.append(f"")
lines.append(f"🎯 *Consensus High: {t_mean:.1f}°C / {celsius_to_f(t_mean):.1f}°F*")
lines.append(f"📐 Median: {t_med:.1f}°C / {celsius_to_f(t_med):.1f}°F")
lines.append(f"📉 Range: {t_min:.1f}°C – {t_max:.1f}°C ({celsius_to_f(t_min):.1f}°F – {celsius_to_f(t_max):.1f}°F)")
lines.append(f"📏 Std dev: ±{t_stdev:.1f}°C")
lines.append(f"🔒 Confidence: {confidence_label} {confidence_note}")
lines.append(f"")
lines.append(f"*DISTRIBUTION BY TEMPERATURE BAND*")
lines.append(f"┌{'─'*36}┐")
lines.append(f"│ {'Temp Band':<16} {'Bar':<12} {'%':>5} │")
lines.append(f"├{'─'*36}┤")

for bucket in sorted_buckets:
count = len(bands[bucket])
pct = count / n_total * 100
bar_len = max(1, round(count / max_count * 10))
bar = "█" * bar_len + "░" * (10 - bar_len)
hi_c = bucket + 1
lo_f = celsius_to_f(bucket)
hi_f = celsius_to_f(hi_c)
band_label = f"{bucket}–{hi_c}°C ({lo_f:.0f}–{hi_f:.0f}°F)"
peak_marker = " ◀" if bucket == sorted_buckets[
max(range(len(sorted_buckets)), key=lambda i: len(bands[sorted_buckets[i]]))
] else ""
lines.append(f"│ {band_label:<16} {bar} {pct:>4.1f}%{peak_marker} │")

lines.append(f"└{'─'*36}┘")
lines.append(f"")
lines.append(f"*MODEL BREAKDOWN (deterministic)*")
lines.append(f"{'─'*34}")
if det:
for label, temp_c in sorted(det.items(), key=lambda x: x[1]):
temp_f = celsius_to_f(temp_c)
diff = temp_c - t_mean
arrow = "▲" if diff > 0.5 else ("▼" if diff < -0.5 else "≈")
lines.append(f"{arrow} {temp_c:.1f}°C ({temp_f:.1f}°F) — {label.strip()}")
else:
lines.append("_No deterministic model data returned._")

if gfs:
g_mean = statistics.mean(gfs)
g_min = min(gfs)
g_max = max(gfs)
lines.append(f"")
lines.append(f"*GFS Ensemble ({len(gfs)} members)*")
lines.append(f" Mean: {g_mean:.1f}°C | Range: {g_min:.1f}–{g_max:.1f}°C")

if ecmwf:
e_mean = statistics.mean(ecmwf)
e_min = min(ecmwf)
e_max = max(ecmwf)
lines.append(f"")
lines.append(f"*ECMWF Ensemble ({len(ecmwf)} members)*")
lines.append(f" Mean: {e_mean:.1f}°C | Range: {e_min:.1f}–{e_max:.1f}°C")

lines.append(f"")
lines.append(f"_Data: Open-Meteo · ECMWF · NOAA · DWD · Météo-France_")
lines.append(f"_CMC · BOM · UKMO · JMA · CMA · ARPAE_")

return "\n".join(lines)
```

# ─── TELEGRAM HANDLERS ────────────────────────────────────────

HELP_TEXT = “””
🌤 *Weather Consensus Bot*

I analyze 40+ forecast data points from the world’s top meteorological agencies and give you a consensus high temperature for any location.

*Sources include:*
• ECMWF (Europe)
• NOAA GFS + 31-member ensemble (USA)
• DWD ICON (Germany)
• Météo-France (France)
• CMC GEM (Canada)
• BOM ACCESS-G (Australia)
• UK Met Office
• JMA (Japan)
• CMA GRAPES (China)
• ARPAE COSMO (Italy)

*How to use:*
`/weather <location>`

*Examples:*
`/weather Denver, CO`
`/weather London`
`/weather Tokyo`
`/weather Sydney, Australia`
`/weather Paris, France`

Just type a city name after /weather and I’ll do the rest!
“””

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
await update.message.reply_text(HELP_TEXT, parse_mode=“Markdown”)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
await update.message.reply_text(HELP_TEXT, parse_mode=“Markdown”)

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
“”“Handle /weather <location>.”””
if not context.args:
await update.message.reply_text(
“Please provide a location.\nExample: `/weather Denver, CO`”,
parse_mode=“Markdown”,
)
return

```
location = " ".join(context.args)
await update.message.reply_text(
f"🔍 Fetching forecasts for *{location}*...\n_(Querying 10 models + ensemble data — this takes ~10 seconds)_",
parse_mode="Markdown",
)

# Geocode
geo = await geocode_location(location)
if not geo:
await update.message.reply_text(
f"❌ Couldn't find coordinates for *{location}*.\nTry a more specific name (e.g., `Denver, CO` instead of `Denver`).",
parse_mode="Markdown",
)
return

logger.info(f"Fetching weather for {geo['display']} ({geo['lat']}, {geo['lon']})")

# Fetch all forecasts concurrently
try:
forecast_data = await gather_all_forecasts(geo["lat"], geo["lon"])
except Exception as e:
logger.error(f"Forecast fetch error: {e}")
await update.message.reply_text("⚠️ Network error fetching forecasts. Please try again in a moment.")
return

report = build_report(geo["display"], forecast_data)

try:
await update.message.reply_text(report, parse_mode="Markdown")
except Exception:
# Fallback: send without markdown if formatting breaks
await update.message.reply_text(report)
```

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
“”“Handle plain text messages — treat them as location queries.”””
text = update.message.text.strip()
if text.startswith(”/”):
return
# Route plain text to weather handler
context.args = text.split()
await weather_command(update, context)

# ─── MAIN ─────────────────────────────────────────────────────

def main():
if BOT_TOKEN == “PASTE_YOUR_BOT_TOKEN_HERE”:
print(
“\n❌ ERROR: No bot token set.\n”
“ Edit BOT_TOKEN in this file or set the environment variable:\n”
“ export TELEGRAM_BOT_TOKEN=‘your_token_here’\n”
)
return

```
print("🌤 Weather Consensus Bot starting...")
print(f" Models: {len(DETERMINISTIC_MODELS)} deterministic + GFS/ECMWF ensembles")
print(" Press Ctrl+C to stop.\n")

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("weather", weather_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))

app.run_polling(allowed_updates=Update.ALL_TYPES)
```

if **name** == “**main**”:
main()
