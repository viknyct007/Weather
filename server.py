from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
import json
import os
import statistics
import time

LAT = 40.78
LON = -73.97

UA = "CentralParkWeather/3.0"

# --------------------------------------------------
# BASIC HTTP REQUEST
# --------------------------------------------------

def get_json(url):
    request = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/geo+json, application/json"
        }
    )

    with urlopen(request, timeout=20) as response:
        return json.loads(response.read())


# --------------------------------------------------
# TEMPERATURE HELPERS
# --------------------------------------------------

def c_to_f(c):
    return (float(c) * 9 / 5) + 32


def round_temp(value):
    if value is None:
        return None

    return round(float(value), 1)


# --------------------------------------------------
# NWS / WEATHER.GOV
# --------------------------------------------------

def get_nws():

    point = get_json(
        f"https://api.weather.gov/points/{LAT},{LON}"
    )

    properties = point["properties"]

    forecast_url = properties["forecastHourly"]
    stations_url = properties["observationStations"]

    forecast = get_json(forecast_url)

    stations = get_json(stations_url)

    station = None

    for feature in stations.get("features", []):

        identifier = (
            feature.get("properties", {})
            .get("stationIdentifier")
        )

        if identifier == "KNYC":
            station = feature
            break

    if station is None:
        raise Exception("KNYC station not found")

    station_url = station["id"]

    # Latest observation
    latest = get_json(
        station_url + "/observations/latest"
    )["properties"]

    # Past six hours
    now = datetime.now(timezone.utc)

    start = now - timedelta(hours=6)

    params = urlencode({
        "start": start.isoformat(),
        "end": now.isoformat()
    })

    history_url = (
        station_url +
        "/observations?" +
        params
    )

    history = get_json(history_url)

    return {
        "forecast": forecast
        .get("properties", {})
        .get("periods", []),

        "current": latest,

        "history": history.get(
            "features",
            []
        )
    }


# --------------------------------------------------
# OPEN-METEO
# --------------------------------------------------

def get_open_meteo():

    params = urlencode({
        "latitude": LAT,
        "longitude": LON,
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": 2
    })

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + params
    )

    return get_json(url)


# --------------------------------------------------
# OPTIONAL WEATHERAPI
# --------------------------------------------------

def get_weatherapi():

    key = os.environ.get(
        "WEATHERAPI_KEY"
    )

    if not key:
        return None

    params = urlencode({
        "key": key,
        "q": f"{LAT},{LON}",
        "days": 2,
        "aqi": "no",
        "alerts": "no"
    })

    url = (
        "https://api.weatherapi.com/v1/forecast.json?"
        + params
    )

    return get_json(url)


# --------------------------------------------------
# NWS CURRENT CONDITIONS
# --------------------------------------------------

def current_conditions(nws):

    obs = nws.get(
        "current",
        {}
    )

    temperature = (
        obs.get("temperature", {})
        .get("value")
    )

    wind = (
        obs.get("windSpeed", {})
        .get("value")
    )

    if temperature is not None:
        temperature = c_to_f(
            temperature
        )

    if wind is not None:
        wind = float(wind) * 0.621371

    humidity = (
        obs.get("relativeHumidity", {})
        .get("value")
    )

    return {
        "temperatureF": round_temp(
            temperature
        ),

        "humidity": humidity,

        "windMph": round_temp(
            wind
        ),

        "description": obs.get(
            "textDescription"
        ),

        "textDescription": obs.get(
            "textDescription"
        )
    }


# --------------------------------------------------
# PAST SIX-HOUR HIGH / LOW
# --------------------------------------------------

def get_six_hour_extremes(nws):

    observations = []

    for feature in nws.get(
        "history",
        []
    ):

        properties = feature.get(
            "properties",
            {}
        )

        value = (
            properties
            .get("temperature", {})
            .get("value")
        )

        timestamp = properties.get(
            "timestamp"
        )

        if value is None:
            continue

        observations.append({
            "temperature": c_to_f(
                value
            ),
            "time": timestamp
        })

    if not observations:

        return {
            "high": None,
            "low": None
        }

    high = max(
        observations,
        key=lambda x: x["temperature"]
    )

    low = min(
        observations,
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


# --------------------------------------------------
# BUILD CONSENSUS FORECAST
# --------------------------------------------------

def build_forecast(
    nws,
    open_meteo,
    weatherapi
):

    # Each hour gets a list of provider values.
    hourly = {}

    # ----------------------------------------------
    # NWS
    # ----------------------------------------------

    for period in nws.get(
        "forecast",
        []
    ):

        timestamp = period.get(
            "startTime"
        )

        temperature = period.get(
            "temperature"
        )

        if timestamp is None:
            continue

        if temperature is None:
            continue

        hourly.setdefault(
            timestamp,
            {}
        )["NWS"] = float(
            temperature
        )

    # ----------------------------------------------
    # OPEN-METEO
    # ----------------------------------------------

    if open_meteo:

        times = (
            open_meteo
            .get("hourly", {})
            .get("time", [])
        )

        temperatures = (
            open_meteo
            .get("hourly", {})
            .get("temperature_2m", [])
        )

        for local_time, temperature in zip(
            times,
            temperatures
        ):

            if temperature is None:
                continue

            try:

                dt = datetime.fromisoformat(
                    local_time
                )

                # Open-Meteo gives local New York
                # time because timezone was requested.
                #
                # Convert it to UTC so it lines
                # up with NWS timestamps.

                eastern = timezone(
                    timedelta(hours=-4)
                )

                utc_time = dt.replace(
                    tzinfo=eastern
                ).astimezone(
                    timezone.utc
                )

                timestamp = (
                    utc_time
                    .isoformat()
                    .replace(
                        "+00:00",
                        "Z"
                    )
                )

                hourly.setdefault(
                    timestamp,
                    {}
                )["Open-Meteo"] = float(
                    temperature
                )

            except Exception:
                pass

    # ----------------------------------------------
    # WEATHERAPI
    # ----------------------------------------------

    if weatherapi:

        for day in (
            weatherapi
            .get("forecast", {})
            .get("forecastday", [])
        ):

            for hour in day.get(
                "hour",
                []
            ):

                local_time = hour.get(
                    "time"
                )

                temperature = hour.get(
                    "temp_f"
                )

                if (
                    local_time is None
                    or temperature is None
                ):
                    continue

                # WeatherAPI local time
                # is converted to UTC.
                try:

                    dt = datetime.fromisoformat(
                        local_time
                    )

                    eastern = timezone(
                        timedelta(hours=-4)
                    )

                    utc_time = dt.replace(
                        tzinfo=eastern
                    ).astimezone(
                        timezone.utc
                    )

                    timestamp = (
                        utc_time
                        .isoformat()
                        .replace(
                            "+00:00",
                            "Z"
                        )
                    )

                    hourly.setdefault(
                        timestamp,
                        {}
                    )["WeatherAPI"] = float(
                        temperature
                    )

                except Exception:
                    pass

    # ----------------------------------------------
    # CONSENSUS
    # ----------------------------------------------

    result = []

    for timestamp, sources in hourly.items():

        values = list(
            sources.values()
        )

        if not values:
            continue

        # Median is used instead of "most common"
        # because weather temperatures are continuous
        # values and usually won't be identical.

        consensus = statistics.median(
            values
        )

        result.append({
            "time": timestamp,
            "startTime": timestamp,

            "temperature": round_temp(
                consensus
            ),

            "temperatureUnit": "F",
            "unit": "F",

            "shortForecast": "Consensus forecast",
            "forecast": "Consensus forecast",

            "sources": {
                name: round_temp(value)
                for name, value in sources.items()
            },

            "sourceCount": len(
                sources
            )
        })

    result.sort(
        key=lambda x: x["time"]
    )

    return result[:24]


# --------------------------------------------------
# MAIN WEATHER FUNCTION
# --------------------------------------------------

def weather():

    errors = []

    # NWS
    try:

        nws = get_nws()

    except Exception as error:

        nws = {
            "forecast": [],
            "current": {},
            "history": []
        }

        errors.append(
            "NWS: " + str(error)
        )

    # Open-Meteo
    try:

        open_meteo = get_open_meteo()

    except Exception as error:

        open_meteo = None

        errors.append(
            "Open-Meteo: " + str(error)
        )

    # WeatherAPI
    try:

        weatherapi = get_weatherapi()

    except Exception as error:

        weatherapi = None

        errors.append(
            "WeatherAPI: " + str(error)
        )

    forecast = build_forecast(
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

        "fetchedAt":
            time.time() * 1000,

        "current":
            current_conditions(nws),

        "sixHour":
            get_six_hour_extremes(nws),

        "forecast":
            forecast,

        "providers": {
            "NWS":
                len(
                    nws.get(
                        "forecast",
                        []
                    )
                ) > 0,

            "Open-Meteo":
                open_meteo is not None,

            "WeatherAPI":
                weatherapi is not None
        },

        "errors":
            errors
    }


# --------------------------------------------------
# WEB SERVER
# --------------------------------------------------

class Handler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        try:

            if self.path.startswith(
                "/api/weather"
            ):

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
                ) as file:

                    data = file.read()

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.end_headers()

            self.wfile.write(
                data
            )

        except Exception as error:

            data = json.dumps({
                "error": str(error)
            }).encode()

            self.send_response(500)

            self.send_header(
                "Content-Type",
                "application/json"
            )

            self.send_header(
                "Cache-Control",
                "no-store"
            )

            self.end_headers()

            self.wfile.write(
                data
            )

    def log_message(
        self,
        format,
        *args
    ):
        pass


# --------------------------------------------------
# START SERVER
# --------------------------------------------------

port = int(
    os.environ.get(
        "PORT",
        "10000"
    )
)

print(
    f"Central Park Weather running on port {port}"
)

server = ThreadingHTTPServer(
    ("0.0.0.0", port),
    Handler
)

server.serve_forever()
