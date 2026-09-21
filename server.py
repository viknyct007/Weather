from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import statistics
import time

LAT = 40.78
LON = -73.97
UA = "CentralParkWeather/4.0"


# =========================================================
# HTTP JSON
# =========================================================

def get_json(url):
    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json"
        }
    )

    with urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def c_to_f(c):
    return float(c) * 9 / 5 + 32


def round_temp(value):
    if value is None:
        return None
    return round(float(value), 1)


# =========================================================
# NWS
# =========================================================

def get_nws():

    point = get_json(
        f"https://api.weather.gov/points/{LAT},{LON}"
    )

    p = point["properties"]

    forecast = get_json(
        p["forecastHourly"]
    )

    stations = get_json(
        p["observationStations"]
    )

    station = None

    for feature in stations.get("features", []):
        if (
            feature.get("properties", {})
            .get("stationIdentifier")
            == "KNYC"
        ):
            station = feature
            break

    if not station:
        raise Exception("KNYC station not found")

    station_url = station["id"]

    current = get_json(
        station_url +
        "/observations/latest"
    )["properties"]

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=6)

    params = urlencode({
        "start": start.isoformat(),
        "end": now.isoformat()
    })

    history = get_json(
        station_url +
        "/observations?" +
        params
    )

    return {
        "forecast":
            forecast["properties"]["periods"],

        "current":
            current,

        "history":
            history.get("features", [])
    }


# =========================================================
# OPEN-METEO
# =========================================================

def get_open_meteo():

    params = urlencode({
        "latitude": LAT,
        "longitude": LON,
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": 2
    })

    return get_json(
        "https://api.open-meteo.com/v1/forecast?"
        + params
    )


# =========================================================
# OPTIONAL WEATHERAPI
# =========================================================

def get_weatherapi():

    key = os.environ.get("WEATHERAPI_KEY")

    if not key:
        return None

    params = urlencode({
        "key": key,
        "q": f"{LAT},{LON}",
        "days": 2,
        "aqi": "no",
        "alerts": "no"
    })

    return get_json(
        "https://api.weatherapi.com/v1/forecast.json?"
        + params
    )


# =========================================================
# CURRENT CONDITIONS
# =========================================================

def current_conditions(nws):

    obs = nws["current"]

    temp = (
        obs.get("temperature", {})
        .get("value")
    )

    wind = (
        obs.get("windSpeed", {})
        .get("value")
    )

    humidity = (
        obs.get("relativeHumidity", {})
        .get("value")
    )

    if temp is not None:
        temp = c_to_f(temp)

    if wind is not None:
        wind = float(wind) * 0.621371

    return {
        "temperatureF": round_temp(temp),
        "humidity": humidity,
        "windMph": round_temp(wind),
        "description":
            obs.get("textDescription"),
        "textDescription":
            obs.get("textDescription")
    }


# =========================================================
# PAST 6 HOURS
# =========================================================

def six_hour_extremes(nws):

    observations = []

    for feature in nws["history"]:

        props = feature.get(
            "properties",
            {}
        )

        value = (
            props
            .get("temperature", {})
            .get("value")
        )

        timestamp = props.get(
            "timestamp"
        )

        if value is None:
            continue

        observations.append({
            "temperature":
                c_to_f(value),
            "time":
                timestamp
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
            "temperature":
                round_temp(
                    high["temperature"]
                ),
            "time":
                high["time"]
        },

        "low": {
            "temperature":
                round_temp(
                    low["temperature"]
                ),
            "time":
                low["time"]
        }
    }


# =========================================================
# FORECAST CONSENSUS
# =========================================================

def build_consensus(
    nws,
    open_meteo,
    weatherapi
):

    hourly = {}

    # -------------------------
    # NWS
    # -------------------------

    for p in nws["forecast"]:

        timestamp = p.get(
            "startTime"
        )

        temp = p.get(
            "temperature"
        )

        if timestamp and temp is not None:

            dt = datetime.fromisoformat(
                timestamp.replace(
                    "Z",
                    "+00:00"
                )
            )

            key = dt.astimezone(
                timezone.utc
            ).strftime(
                "%Y-%m-%dT%H:00:00Z"
            )

            hourly.setdefault(
                key,
                {}
            )["NWS"] = float(temp)

    # -------------------------
    # OPEN-METEO
    # -------------------------

    if open_meteo:

        times = (
            open_meteo
            .get("hourly", {})
            .get("time", [])
        )

        temps = (
            open_meteo
            .get("hourly", {})
            .get("temperature_2m", [])
        )

        eastern = ZoneInfo(
            "America/New_York"
        )

        for local_time, temp in zip(
            times,
            temps
        ):

            if temp is None:
                continue

            try:

                dt = datetime.fromisoformat(
                    local_time
                )

                dt = dt.replace(
                    tzinfo=eastern
                )

                key = dt.astimezone(
                    timezone.utc
                ).strftime(
                    "%Y-%m-%dT%H:00:00Z"
                )

                hourly.setdefault(
                    key,
                    {}
                )["Open-Meteo"] = float(
                    temp
                )

            except Exception:
                pass

    # -------------------------
    # WEATHERAPI
    # -------------------------

    if weatherapi:

        eastern = ZoneInfo(
            "America/New_York"
        )

        for day in (
            weatherapi
            .get("forecast", {})
            .get("forecastday", [])
        ):

            for h in day.get(
                "hour",
                []
            ):

                local_time = h.get(
                    "time"
                )

                temp = h.get(
                    "temp_f"
                )

                if (
                    local_time is None
                    or temp is None
                ):
                    continue

                try:

                    dt = datetime.fromisoformat(
                        local_time
                    )

                    dt = dt.replace(
                        tzinfo=eastern
                    )

                    key = dt.astimezone(
                        timezone.utc
                    ).strftime(
                        "%Y-%m-%dT%H:00:00Z"
                    )

                    hourly.setdefault(
                        key,
                        {}
                    )["WeatherAPI"] = float(
                        temp
                    )

                except Exception:
                    pass

    # -------------------------
    # CONSENSUS
    # -------------------------

    result = []

    for timestamp, sources in hourly.items():

        if not sources:
            continue

        values = list(
            sources.values()
        )

        # Median = consensus temperature
        consensus = statistics.median(
            values
        )

        # Get NWS description if available
        description = "Consensus"

        for p in nws["forecast"]:

            if p.get("startTime"):

                dt = datetime.fromisoformat(
                    p["startTime"].replace(
                        "Z",
                        "+00:00"
                    )
                )

                key = dt.astimezone(
                    timezone.utc
                ).strftime(
                    "%Y-%m-%dT%H:00:00Z"
                )

                if key == timestamp:

                    description = p.get(
                        "shortForecast",
                        "Consensus"
                    )

                    break

        result.append({

            "time":
                timestamp,

            "startTime":
                timestamp,

            "temperature":
                round_temp(
                    consensus
                ),

            "temperatureUnit":
                "F",

            "unit":
                "F",

            "shortForecast":
                description,

            "forecast":
                description,

            "sources": {
                name:
                    round_temp(value)
                for name, value
                in sources.items()
            },

            "sourceCount":
                len(sources)

        })

    result.sort(
        key=lambda x: x["time"]
    )

    return result[:24]


# =========================================================
# WEATHER DATA
# =========================================================

def weather():

    errors = []

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

    try:
        open_meteo = get_open_meteo()
    except Exception as e:
        open_meteo = None

        errors.append(
            "Open-Meteo: " + str(e)
        )

    try:
        weatherapi = get_weatherapi()
    except Exception as e:
        weatherapi = None

        errors.append(
            "WeatherAPI: " + str(e)
        )

    return {

        "station": "KNYC",

        "location": {
            "name":
                "Central Park",
            "latitude":
                LAT,
            "longitude":
                LON
        },

        "fetchedAt":
            time.time() * 1000,

        "current":
            current_conditions(nws),

        "sixHour":
            six_hour_extremes(nws),

        "forecast":
            build_consensus(
                nws,
                open_meteo,
                weatherapi
            ),

        "providers": {
            "NWS":
                bool(
                    nws["forecast"]
                ),

            "Open-Meteo":
                open_meteo is not None,

            "WeatherAPI":
                weatherapi is not None
        },

        "errors":
            errors
    }


# =========================================================
# WEBSITE
# =========================================================

HTML = r'''
<!DOCTYPE html>
<html>
<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Central Park Weather</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #0d0f12;
    color: white;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Arial,
        sans-serif;
}

.container {
    max-width: 700px;
    margin: auto;
    padding: 16px;
}

h1 {
    margin: 5px 0;
    font-size: 29px;
}

.subtitle {
    color: #858b95;
    margin-bottom: 18px;
}

.card {
    background: #171a1f;
    border: 1px solid #292d34;
    border-radius: 18px;
    padding: 18px;
    margin-bottom: 15px;
}

.title {
    font-size: 19px;
    font-weight: 700;
    margin-bottom: 15px;
}

.current {
    text-align: center;
    padding: 28px 15px;
}

.label {
    color: #888f99;
    font-size: 12px;
    letter-spacing: 1px;
}

.temperature {
    font-size: 62px;
    font-weight: 700;
    margin: 8px 0;
}

.description {
    color: #c5cad1;
    font-size: 18px;
}

.updated {
    color: #707782;
    font-size: 12px;
    margin-top: 8px;
}

.grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}

.stat {
    background: #20242a;
    border-radius: 14px;
    padding: 15px;
}

.stat-value {
    font-size: 25px;
    font-weight: 700;
}

.stat-time {
    color: #777e88;
    font-size: 13px;
    margin-top: 5px;
}

.sources {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
}

.source {
    background: #20242a;
    border: 1px solid #30353d;
    border-radius: 9px;
    padding: 7px 10px;
    color: #cbd0d7;
    font-size: 13px;
}

.hour {
    padding: 14px 0;
    border-bottom: 1px solid #292d34;
}

.hour:last-child {
    border-bottom: 0;
}

.hour-main {
    display: grid;
    grid-template-columns:
        23% 22% 38% 17%;
    align-items: center;
}

.hour-time {
    font-weight: 600;
    color: #c8ccd3;
}

.hour-temp {
    font-size: 19px;
    font-weight: 700;
}

.hour-weather {
    color: #aeb4bd;
    font-size: 13px;
}

.hour-count {
    text-align: right;
    color: #70b8ff;
    font-size: 11px;
}

.provider-values {
    margin-top: 7px;
    color: #737a85;
    font-size: 11px;
}

button {
    width: 100%;
    border: 0;
    border-radius: 13px;
    padding: 14px;
    background: white;
    color: #111;
    font-size: 15px;
    font-weight: 700;
}

.error {
    display: none;
    background: #351b1e;
    border: 1px solid #633137;
    color: #ffb9bf;
    padding: 13px;
    border-radius: 13px;
    margin-bottom: 15px;
}

.loading {
    color: #777e88;
    text-align: center;
    padding: 20px;
}

@media(max-width:500px) {

    .temperature {
        font-size: 55px;
    }

    .hour-main {
        grid-template-columns:
            23% 22% 38% 17%;
    }

    .hour-weather {
        font-size: 11px;
    }

}

</style>

</head>

<body>

<div class="container">

<h1>Central Park Weather</h1>

<div class="subtitle">
KNYC • Central Park, New York
</div>

<div id="error" class="error"></div>


<!-- CURRENT -->

<div class="card current">

<div class="label">
CURRENT TEMPERATURE
</div>

<div id="currentTemp"
     class="temperature">
--.-°F
</div>

<div id="description"
     class="description">
Loading...
</div>

<div id="updated"
     class="updated">
Updating...
</div>

</div>


<!-- CURRENT CONDITIONS -->

<div class="card">

<div class="title">
Current Conditions
</div>

<div class="grid">

<div class="stat">

<div class="label">
HUMIDITY
</div>

<div id="humidity"
     class="stat-value">
--%
</div>

</div>

<div class="stat">

<div class="label">
WIND
</div>

<div id="wind"
     class="stat-value">
--.- mph
</div>

</div>

</div>

</div>


<!-- SIX HOUR -->

<div class="card">

<div class="title">
Past 6 Hours
</div>

<div class="grid">

<div class="stat">

<div class="label">
PEAK TEMPERATURE
</div>

<div id="high"
     class="stat-value">
--.-°F
</div>

<div id="highTime"
     class="stat-time">
--
</div>

</div>

<div class="stat">

<div class="label">
LOWEST TEMPERATURE
</div>

<div id="low"
     class="stat-value">
--.-°F
</div>

<div id="lowTime"
     class="stat-time">
--
</div>

</div>

</div>

</div>


<!-- SOURCES -->

<div class="card">

<div class="title">
Forecast Sources
</div>

<div id="sources"
     class="sources">
Loading...
</div>

</div>


<!-- FORECAST -->

<div class="card">

<div class="title">
Next 24 Hours
</div>

<div id="forecast">

<div class="loading">
Loading forecast...
</div>

</div>

</div>


<button onclick="loadWeather()">
Refresh Weather
</button>

</div>


<script>

async function loadWeather() {

    const error =
        document.getElementById("error");

    error.style.display = "none";

    try {

        const response =
            await fetch(
                "/api/weather?t=" +
                Date.now(),
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                "Server returned " +
                response.status
            );
        }

        const data =
            await response.json();

        showWeather(data);

    } catch (e) {

        console.error(e);

        error.textContent =
            "Weather update failed: " +
            e.message;

        error.style.display =
            "block";
    }
}


function time(value) {

    if (!value) return "--";

    const d = new Date(value);

    if (isNaN(d.getTime())) {
        return "--";
    }

    return d.toLocaleTimeString(
        [],
        {
            hour: "numeric",
            minute: "2-digit"
        }
    );
}


function showWeather(data) {

    const current =
        data.current || {};


    // Current temperature

    if (current.temperatureF != null) {

        document.getElementById(
            "currentTemp"
        ).textContent =
            Number(
                current.temperatureF
            ).toFixed(1) +
            "°F";
    }


    // Description

    document.getElementById(
        "description"
    ).textContent =
        current.description ||
        "Conditions unavailable";


    // Humidity

    if (current.humidity != null) {

        document.getElementById(
            "humidity"
        ).textContent =
            Number(
                current.humidity
            ).toFixed(0) +
            "%";
    }


    // Wind

    if (current.windMph != null) {

        document.getElementById(
            "wind"
        ).textContent =
            Number(
                current.windMph
            ).toFixed(1) +
            " mph";
    }


    // Updated

    document.getElementById(
        "updated"
    ).textContent =
        "Updated " +
        time(data.fetchedAt);


    // Six hour high

    if (
        data.sixHour &&
        data.sixHour.high
    ) {

        document.getElementById(
            "high"
        ).textContent =
            Number(
                data.sixHour.high.temperature
            ).toFixed(1) +
            "°F";

        document.getElementById(
            "highTime"
        ).textContent =
            time(
                data.sixHour.high.time
            );
    }


    // Six hour low

    if (
        data.sixHour &&
        data.sixHour.low
    ) {

        document.getElementById(
            "low"
        ).textContent =
            Number(
                data.sixHour.low.temperature
            ).toFixed(1) +
            "°F";

        document.getElementById(
            "lowTime"
        ).textContent =
            time(
                data.sixHour.low.time
            );
    }


    // Sources

    const sourceBox =
        document.getElementById(
            "sources"
        );

    sourceBox.innerHTML = "";

    let count = 0;

    Object.entries(
        data.providers || {}
    ).forEach(
        ([name, active]) => {

            if (!active) return;

            count++;

            const span =
                document.createElement(
                    "span"
                );

            span.className =
                "source";

            span.textContent =
                "✓ " + name;

            sourceBox.appendChild(
                span
            );
        }
    );

    if (!count) {

        sourceBox.textContent =
            "No forecast providers available";
    }


    // Forecast

    const box =
        document.getElementById(
            "forecast"
        );

    box.innerHTML = "";


    (data.forecast || [])
        .slice(0, 24)
        .forEach(
            p => {

                const row =
                    document.createElement(
                        "div"
                    );

                row.className =
                    "hour";


                let temp = "--.-°F";

                if (
                    p.temperature != null
                ) {

                    temp =
                        Number(
                            p.temperature
                        ).toFixed(1) +
                        "°F";
                }


                let providerValues = "";

                if (p.sources) {

                    providerValues =
                        Object.entries(
                            p.sources
                        )
                        .map(
                            ([name, value]) =>
                                name +
                                ": " +
                                Number(value)
                                .toFixed(1) +
                                "°F"
                        )
                        .join(" • ");
                }


                row.innerHTML = `

<div class="hour-main">

<div class="hour-time">
${time(p.time)}
</div>

<div class="hour-temp">
${temp}
</div>

<div class="hour-weather">
${p.shortForecast || "Consensus"}
</div>

<div class="hour-count">
${p.sourceCount || 0} source${p.sourceCount == 1 ? "" : "s"}
</div>

</div>

<div class="provider-values">
${providerValues}
</div>

`;

                box.appendChild(row);

            }
        );

}


loadWeather();

setInterval(
    loadWeather,
    5 * 60 * 1000
);

</script>

</body>
</html>
'''


# =========================================================
# SERVER
# =========================================================

class Handler(BaseHTTPRequestHandler):

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

                data = HTML.encode(
                    "utf-8"
                )

                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                )

            self.send_header(
                "Cache-Control",
                "no-store, no-cache, must-revalidate"
            )

            self.send_header(
                "Pragma",
                "no-cache"
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


    def log_message(
        self,
        format,
        *args
    ):
        pass


# =========================================================
# START
# =========================================================

port = int(
    os.environ.get(
        "PORT",
        "10000"
    )
)

print(
    "Central Park Weather running on port",
    port
)

server = ThreadingHTTPServer(
    ("0.0.0.0", port),
    Handler
)

server.serve_forever()
