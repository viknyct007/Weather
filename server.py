from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import quote
from datetime import datetime, timezone, timedelta
import json
import os
import statistics
import time

LAT, LON = 40.78, -73.97
UA = "CentralParkWeather/2.0"

def get_json(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def f_to_c(f):
    return (f - 32) * 5 / 9

def c_to_f(c):
    return c * 9 / 5 + 32

def round_temp(v):
    return None if v is None else round(float(v), 1)

# ---------------------------------------------------------
# NWS / WEATHER.GOV
# ---------------------------------------------------------

def get_nws():
    point = get_json(
        f"https://api.weather.gov/points/{LAT},{LON}"
    )

    forecast_url = point["properties"]["forecastHourly"]

    forecast = get_json(forecast_url)

    stations = get_json(
        point["properties"]["observationStations"]
    )

    station = next(
        s for s in stations["features"]
        if s["properties"].get("stationIdentifier") == "KNYC"
    )

    station_url = station["id"]

    latest = get_json(
        station_url + "/observations/latest"
    )["properties"]

    # Past 6 hours
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=6)

    history_url = (
        station_url +
        "/observations?start=" +
        quote(start.isoformat()) +
        "&end=" +
        quote(now.isoformat())
    )

    history = get_json(history_url)

    return {
        "forecast": forecast["properties"]["periods"],
        "current": latest,
        "history": history.get("features", [])
    }


# ---------------------------------------------------------
# OPEN-METEO
# ---------------------------------------------------------

def get_open_meteo():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}"
        f"&longitude={LON}"
        "&hourly=temperature_2m"
        "&temperature_unit=fahrenheit"
        "&timezone=America%2FNew_York"
        "&forecast_days=2"
    )

    return get_json(url)


# ---------------------------------------------------------
# WEATHERAPI
# ---------------------------------------------------------

def get_weatherapi():
    key = os.environ.get("WEATHERAPI_KEY")

    if not key:
        return None

    url = (
        "https://api.weatherapi.com/v1/forecast.json"
        f"?key={quote(key)}"
        f"&q={LAT},{LON}"
        "&days=2"
        "&aqi=no"
        "&alerts=no"
    )

    return get_json(url)


# ---------------------------------------------------------
# CONSENSUS FORECAST
# ---------------------------------------------------------

def build_consensus(nws, open_meteo, weatherapi):
    sources = {}

    # NWS
    for p in nws["forecast"]:
        t = p["startTime"]

        temp = p.get("temperature")

        if temp is not None:
            sources.setdefault(t, {})["NWS"] = float(temp)

    # Open-Meteo
    if open_meteo:
        times = open_meteo["hourly"]["time"]
        temps = open_meteo["hourly"]["temperature_2m"]

        for t, temp in zip(times, temps):
            if temp is None:
                continue

            try:
                dt = datetime.fromisoformat(t)

                # Convert to the same ISO format used by NWS
                iso = dt.replace(
                    tzinfo=timezone(
                        timedelta(hours=-4)
                    )
                ).astimezone(timezone.utc).isoformat()

                sources.setdefault(iso, {})["Open-Meteo"] = float(temp)

            except Exception:
                pass

    # WeatherAPI
    if weatherapi:
        for day in weatherapi.get("forecast", {}).get("forecastday", []):
            for h in day.get("hour", []):
                t = h.get("time")

                temp = h.get("temp_f")

                if t and temp is not None:
                    sources.setdefault(
                        t.replace(" ", "T"),
                        {}
                    )["WeatherAPI"] = float(temp)

    result = []

    for timestamp, values in sources.items():

        if not values:
            continue

        temps = list(values.values())

        consensus = statistics.median(temps)

        result.append({
            "time": timestamp,
            "startTime": timestamp,

            "temperature": round_temp(consensus),
            "temperatureUnit": "F",
            "unit": "F",

            "sources": {
                k: round_temp(v)
                for k, v in values.items()
            },

            "sourceCount": len(values)
        })

    result.sort(key=lambda x: x["time"])

    return result[:24]


# ---------------------------------------------------------
# CURRENT CONDITIONS
# ---------------------------------------------------------

def current_conditions(nws):
    obs = nws["current"]

    temp = obs.get("temperature", {}).get("value")
    wind = obs.get("windSpeed", {}).get("value")

    if temp is not None:
        temp = c_to_f(temp)

    if wind is not None:
        wind = wind * 0.621371

    return {
        "temperatureF": round_temp(temp),

        "humidity": (
            obs.get("relativeHumidity", {})
            .get("value")
        ),

        "windMph": round_temp(wind),

        "description": obs.get("textDescription"),

        "textDescription": obs.get(
            "textDescription"
        )
    }


# ---------------------------------------------------------
# PAST 6-HOUR HIGH / LOW
# ---------------------------------------------------------

def six_hour_extremes(nws):
    temps = []

    for feature in nws["history"]:

        props = feature.get("properties", {})

        temp = props.get(
            "temperature", {}
        ).get("value")

        timestamp = props.get("timestamp")

        if temp is None:
            continue

        f = c_to_f(temp)

        temps.append({
            "temperature": f,
            "time": timestamp
        })

    if not temps:
        return {
            "high": None,
            "low": None
        }

    high = max(
        temps,
        key=lambda x: x["temperature"]
    )

    low = min(
        temps,
        key=lambda x: x["temperature"]
    )

    return {
        "high": {
            "temperature": round_temp(
                high["temperature"]
            ),
            "time": high["time"]
        },

        "low": {
            "temperature": round_temp(
                low["temperature"]
            ),
            "time": low["time"]
        }
    }


# ---------------------------------------------------------
# MAIN WEATHER ENDPOINT
# ---------------------------------------------------------

def weather():

    errors = []

    # NWS
    try:
        nws = get_nws()
    except Exception as e:
        nws = {
            "forecast": [],
            "current": {},
            "history": []
        }

        errors.append(
            "NWS: " + str(e)
        )

    # Open-Meteo
    try:
        open_meteo = get_open_meteo()
    except Exception as e:
        open_meteo = None

        errors.append(
            "Open-Meteo: " + str(e)
        )

    # WeatherAPI
    try:
        weatherapi = get_weatherapi()
    except Exception as e:
        weatherapi = None

        errors.append(
            "WeatherAPI: " + str(e)
        )

    consensus = build_consensus(
        nws,
        open_meteo,
        weatherapi
    )

    return {
        "station": "KNYC",

        "location": {
            "name": "Central Park",
            "latitude": LAT,
            "longitude": LON
        },

        "fetchedAt": time.time() * 1000,

        "current": current_conditions(nws),

        "sixHour": six_hour_extremes(nws),

        "forecast": consensus,

        "providers": {
            "NWS": bool(nws["forecast"]),
            "Open-Meteo": open_meteo is not None,
            "WeatherAPI": weatherapi is not None
        },

        "errors": errors
    }


# ---------------------------------------------------------
# SERVER
# ---------------------------------------------------------

class Handler(BaseHTTPRequestHandler):

    def do_GET(self):

        try:

            if self.path.startswith("/api/weather"):

                data = json.dumps(
                    weather()
                ).encode()

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "application/json"
                )

            else:

                with open(
                    "index.html",
                    "rb"
                ) as f:
                    data = f.read()

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html"
                )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.end_headers()

            self.wfile.write(data)

        except Exception as e:

            data = json.dumps({
                "error": str(e)
            }).encode()

            self.send_response(500)

            self.send_header(
                "Content-Type",
                "application/json"
            )

            self.end_headers()

            self.wfile.write(data)

    def log_message(self, *args):
        pass


port = int(
    os.environ.get(
        "PORT",
        10000
    )
)

print(
    f"Server running on port {port}"
)

server = ThreadingHTTPServer(
    ("0.0.0.0", port),
    Handler
)

server.serve_forever()
