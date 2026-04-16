#!/usr/bin/env python3
"""
WEATHER CONSENSUS BOT - Telegram

Fetches high-temperature forecasts from 40+ independent
meteorological data points (10 deterministic models +
31-member GFS ensemble) via Open-Meteo (free, no API key).

SETUP:
1. Install dependencies:
   pip install python-telegram-bot httpx

2. Create your bot:
   - Open Telegram, search for @BotFather
   - Send /newbot, follow the prompts
   - Copy the token you receive

3. Set your token:
   export TELEGRAM_BOT_TOKEN=your_token_here

4. Run:
   python weather_consensus_bot.py

USAGE IN TELEGRAM:
  /weather New York City
  /weather London, UK
  /weather Tokyo
  /weather Miami, FL
  /start   shows help
"""

import os
import asyncio
import logging
from datetime import date
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

# ---- CONFIGURATION -----------------------------------------------------------

BOT_TOKEN = os.getenv("8589504469:AAFliWw3euwsZdP8zC24KQ0Qs1mEqB7KP34", "8589504469:AAFliWw3euwsZdP8zC24KQ0Qs1mEqB7KP34")

# ---- LOGGING -----------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---- WEATHER MODELS ----------------------------------------------------------

DETERMINISTIC_MODELS = [
    {"model": "ecmwf_ifs025",           "label": "ECMWF IFS 0.25 (Europe)"},
    {"model": "gfs_seamless",           "label": "NOAA GFS (USA)"},
    {"model": "icon_seamless",          "label": "DWD ICON (Germany)"},
    {"model": "meteofrance_seamless",   "label": "Meteo-France ARPEGE (France)"},
    {"model": "gem_seamless",           "label": "CMC GEM (Canada)"},
    {"model": "bom_access_global",      "label": "BOM ACCESS-G (Australia)"},
    {"model": "ukmo_seamless",          "label": "UK Met Office (UK)"},
    {"model": "jma_seamless",           "label": "JMA (Japan)"},
    {"model": "cma_grapes_global",      "label": "CMA GRAPES (China)"},
    {"model": "arpae_cosmo_seamless",   "label": "ARPAE COSMO (Italy)"},
]

OPEN_METEO_URL     = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = 30.0

# ---- GEOCODING ---------------------------------------------------------------

async def geocode_location(location: str):
    params = {"name": location, "count": 1, "language": "en", "format": "json"}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            resp = await client.get(OPEN_METEO_GEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results")
            if results:
                r = results[0]
                parts = [r.get("name", "")]
                if r.get("admin1"):
                    parts.append(r["admin1"])
                if r.get("country"):
                    parts.append(r["country"])
                return {
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "display": ", ".join(filter(None, parts)),
                    "timezone": r.get("timezone", "UTC"),
                }
        except Exception as e:
            logger.warning("Geocode error for '%s': %s", location, e)
        return None

# ---- WEATHER FETCHING --------------------------------------------------------

async def fetch_deterministic_model(client, lat, lon, model):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": model,
        "forecast_days": 1,
        "timezone": "auto",
    }
    try:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        temps = data.get("daily", {}).get("temperature_2m_max", [])
        if temps and temps[0] is not None:
            return float(temps[0])
    except Exception as e:
        logger.debug("Model %s error: %s", model, e)
    return None


async def fetch_gfs_ensemble(client, lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "gfs_seamless",
        "ensemble": "true",
        "forecast_days": 1,
        "timezone": "auto",
    }
    members = []
    try:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        for key, vals in data.get("daily", {}).items():
            if "temperature_2m_max" in key and vals and vals[0] is not None:
                members.append(float(vals[0]))
    except Exception as e:
        logger.debug("GFS ensemble error: %s", e)
    return members


async def fetch_ecmwf_ensemble(client, lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "models": "ecmwf_ifs_ensemble",
        "ensemble": "true",
        "forecast_days": 1,
        "timezone": "auto",
    }
    members = []
    try:
        resp = await client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        for key, vals in data.get("daily", {}).items():
            if "temperature_2m_max" in key and vals and vals[0] is not None:
                members.append(float(vals[0]))
    except Exception as e:
        logger.debug("ECMWF ensemble error: %s", e)
    return members


async def gather_all_forecasts(lat, lon):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        det_tasks = [
            fetch_deterministic_model(client, lat, lon, m["model"])
            for m in DETERMINISTIC_MODELS
        ]
        det_results, gfs_members, ecmwf_members = await asyncio.gather(
            asyncio.gather(*det_tasks),
            fetch_gfs_ensemble(client, lat, lon),
            fetch_ecmwf_ensemble(client, lat, lon),
        )

    deterministic = {}
    for i, val in enumerate(det_results):
        if val is not None:
            deterministic[DETERMINISTIC_MODELS[i]["label"]] = val

    return {
        "deterministic": deterministic,
        "gfs_ensemble": gfs_members,
        "ecmwf_ensemble": ecmwf_members,
    }

# ---- ANALYSIS & FORMATTING ---------------------------------------------------

def celsius_to_f(c):
    return c * 9 / 5 + 32


def build_report(location_display, forecast_data):
    det   = forecast_data["deterministic"]
    gfs   = forecast_data["gfs_ensemble"]
    ecmwf = forecast_data["ecmwf_ensemble"]

    all_temps_c = list(det.values()) + gfs + ecmwf
    n_total = len(all_temps_c)

    if n_total == 0:
        return (
            "Sorry, I couldn't retrieve forecast data for that location.\n"
            "Please try again or rephrase the location name."
        )

    t_mean  = statistics.mean(all_temps_c)
    t_med   = statistics.median(all_temps_c)
    t_min   = min(all_temps_c)
    t_max   = max(all_temps_c)
    t_stdev = statistics.stdev(all_temps_c) if n_total > 1 else 0.0

    if t_stdev < 1.5:
        confidence_label = "Very High"
        confidence_note  = "(models in strong agreement)"
    elif t_stdev < 3.0:
        confidence_label = "High"
        confidence_note  = "(minor spread between models)"
    elif t_stdev < 5.0:
        confidence_label = "Moderate"
        confidence_note  = "(noticeable spread - check closer to the day)"
    else:
        confidence_label = "Low"
        confidence_note  = "(high uncertainty - large model disagreement)"

    bands = {}
    for t in all_temps_c:
        bucket = int(t)
        bands.setdefault(bucket, []).append(t)

    sorted_buckets = sorted(bands.keys())
    max_count = max(len(v) for v in bands.values())
    peak_bucket = sorted_buckets[
        max(range(len(sorted_buckets)), key=lambda i: len(bands[sorted_buckets[i]]))
    ]

    today_str = date.today().strftime("%A, %B %d, %Y")

    lines = []
    lines.append("Location: " + location_display)
    lines.append("Date: " + today_str)
    lines.append("")
    lines.append("HIGH TEMPERATURE CONSENSUS")
    lines.append("-" * 34)
    lines.append("Data points analyzed: " + str(n_total))
    lines.append("  Deterministic models: " + str(len(det)) + "/10")
    if gfs:
        lines.append("  GFS ensemble members: " + str(len(gfs)))
    if ecmwf:
        lines.append("  ECMWF ensemble members: " + str(len(ecmwf)))
    lines.append("")
    lines.append(
        "Consensus High: {:.1f}C / {:.1f}F".format(t_mean, celsius_to_f(t_mean))
    )
    lines.append(
        "Median: {:.1f}C / {:.1f}F".format(t_med, celsius_to_f(t_med))
    )
    lines.append(
        "Range: {:.1f}C - {:.1f}C  ({:.1f}F - {:.1f}F)".format(
            t_min, t_max, celsius_to_f(t_min), celsius_to_f(t_max)
        )
    )
    lines.append("Std dev: +/-{:.1f}C".format(t_stdev))
    lines.append("Confidence: {} {}".format(confidence_label, confidence_note))
    lines.append("")
    lines.append("DISTRIBUTION BY TEMPERATURE BAND")
    lines.append("+" + "-" * 38 + "+")
    lines.append("| {:<17} {:<12} {:>5} |".format("Temp Band", "Bar", "%"))
    lines.append("+" + "-" * 38 + "+")

    for bucket in sorted_buckets:
        count   = len(bands[bucket])
        pct     = count / n_total * 100
        bar_len = max(1, round(count / max_count * 10))
        bar     = "#" * bar_len + "." * (10 - bar_len)
        hi_c    = bucket + 1
        lo_f    = celsius_to_f(bucket)
        hi_f    = celsius_to_f(hi_c)
        label   = "{}-{}C ({:.0f}-{:.0f}F)".format(bucket, hi_c, lo_f, hi_f)
        peak    = " <--" if bucket == peak_bucket else ""
        lines.append("| {:<17} {} {:>4.1f}%{} |".format(label, bar, pct, peak))

    lines.append("+" + "-" * 38 + "+")
    lines.append("")
    lines.append("MODEL BREAKDOWN (deterministic)")
    lines.append("-" * 34)

    if det:
        for label, temp_c in sorted(det.items(), key=lambda x: x[1]):
            temp_f = celsius_to_f(temp_c)
            diff   = temp_c - t_mean
            arrow  = "^" if diff > 0.5 else ("v" if diff < -0.5 else "=")
            lines.append(
                "{} {:.1f}C ({:.1f}F) - {}".format(arrow, temp_c, temp_f, label.strip())
            )
    else:
        lines.append("No deterministic model data returned.")

    if gfs:
        g_mean = statistics.mean(gfs)
        g_min  = min(gfs)
        g_max  = max(gfs)
        lines.append("")
        lines.append("GFS Ensemble ({} members)".format(len(gfs)))
        lines.append(
            "  Mean: {:.1f}C | Range: {:.1f}-{:.1f}C".format(g_mean, g_min, g_max)
        )

    if ecmwf:
        e_mean = statistics.mean(ecmwf)
        e_min  = min(ecmwf)
        e_max  = max(ecmwf)
        lines.append("")
        lines.append("ECMWF Ensemble ({} members)".format(len(ecmwf)))
        lines.append(
            "  Mean: {:.1f}C | Range: {:.1f}-{:.1f}C".format(e_mean, e_min, e_max)
        )

    lines.append("")
    lines.append("Data: Open-Meteo / ECMWF / NOAA / DWD / Meteo-France")
    lines.append("      CMC / BOM / UKMO / JMA / CMA / ARPAE")

    return "\n".join(lines)

# ---- TELEGRAM HANDLERS -------------------------------------------------------

HELP_TEXT = (
    "Weather Consensus Bot\n\n"
    "I analyze 40+ forecast data points from the world's top meteorological\n"
    "agencies and give you a consensus high temperature for any location.\n\n"
    "Sources include:\n"
    "  ECMWF (Europe)\n"
    "  NOAA GFS + 31-member ensemble (USA)\n"
    "  DWD ICON (Germany)\n"
    "  Meteo-France (France)\n"
    "  CMC GEM (Canada)\n"
    "  BOM ACCESS-G (Australia)\n"
    "  UK Met Office\n"
    "  JMA (Japan)\n"
    "  CMA GRAPES (China)\n"
    "  ARPAE COSMO (Italy)\n\n"
    "How to use:\n"
    "  /weather <location>\n\n"
    "Examples:\n"
    "  /weather Denver, CO\n"
    "  /weather London\n"
    "  /weather Tokyo\n"
    "  /weather Sydney, Australia\n"
    "  /weather Paris, France\n"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Please provide a location.\nExample: /weather Denver, CO"
        )
        return

    location = " ".join(context.args)
    await update.message.reply_text(
        "Fetching forecasts for {}...\n"
        "(Querying 10 models + ensemble data - this takes ~10 seconds)".format(location)
    )

    geo = await geocode_location(location)
    if not geo:
        await update.message.reply_text(
            "Could not find coordinates for {}.\n"
            "Try a more specific name (e.g. 'Denver, CO' instead of 'Denver').".format(location)
        )
        return

    logger.info("Fetching weather for %s (%s, %s)", geo["display"], geo["lat"], geo["lon"])

    try:
        forecast_data = await gather_all_forecasts(geo["lat"], geo["lon"])
    except Exception as e:
        logger.error("Forecast fetch error: %s", e)
        await update.message.reply_text(
            "Network error fetching forecasts. Please try again in a moment."
        )
        return

    report = build_report(geo["display"], forecast_data)
    await update.message.reply_text(report)


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    context.args = text.split()
    await weather_command(update, context)

# ---- MAIN --------------------------------------------------------------------

def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print(
            "\nERROR: No bot token set.\n"
            "  Edit BOT_TOKEN in this file or set the environment variable:\n"
            "  export TELEGRAM_BOT_TOKEN='your_token_here'\n"
        )
        return

    print("Weather Consensus Bot starting...")
    print("  Models: {} deterministic + GFS/ECMWF ensembles".format(len(DETERMINISTIC_MODELS)))
    print("  Press Ctrl+C to stop.\n")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   start_command))
    app.add_handler(CommandHandler("help",    help_command))
    app.add_handler(CommandHandler("weather", weather_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
