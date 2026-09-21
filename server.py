from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import statistics
import time


# =========================================================
# CENTRAL PARK LOCATION
# =========================================================

LAT = 40.77898
LON = -73.96925

TIMEZONE = "America/New_York"

UA = "CentralParkWeather/5.0"


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

    if c is None:
        return None

    return float(c) * 9 / 5 + 32


def round_temp(value):

    if value is None:
        return None

    return round(float(value), 1)


def format_time(value):

    if not value:
        return None

    try:

        if value.endswith("Z"):
            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        else:
            dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=ZoneInfo(TIMEZONE)
            )

        return dt.astimezone(
            ZoneInfo(TIMEZONE)
        ).isoformat()

    except Exception:

        return value


# =========================================================
# NWS
# =========================================================

def get_nws():

    point = get_json(
        f"https://api.weather.gov/points/{LAT},{LON}"
    )

    properties = point["properties"]

    forecast_url = properties["forecastHourly"]
    observation_stations_url = properties["observationStations"]

    forecast = get_json(
        forecast_url
    )

    stations = get_json(
        observation_stations_url
    )

    station = None

    for feature in stations.get("features", []):

        station_id = (
            feature
            .get("properties", {})
            .get("stationIdentifier")
        )

        if station_id == "KNYC":

            station = feature
            break

    if not station:

        raise Exception(
            "KNYC station not found"
        )

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

        "latitude":
            LAT,

        "longitude":
            LON,

        "current":
            ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "wind_speed_10m",
                "weather_code"
            ]),

        "hourly":
            "temperature_2m",

        "temperature_unit":
            "fahrenheit",

        "wind_speed_unit":
            "mph",

        "timezone":
            TIMEZONE,

        "forecast_days":
            2

    })

    return get_json(
        "https://api.open-meteo.com/v1/forecast?"
        + params
    )


# =========================================================
# WEATHERAPI
# =========================================================

def get_weatherapi():

    key = os.environ.get(
        "WEATHERAPI_KEY"
    )

    if not key:
        return None

    params = urlencode({

        "key":
            key,

        # Exact Central Park coordinates
        "q":
            f"{LAT},{LON}",

        "days":
            2,

        "aqi":
            "no",

        "alerts":
            "no"

    })

    return get_json(
        "https://api.weatherapi.com/v1/forecast.json?"
        + params
    )


# =========================================================
# NWS CURRENT
# =========================================================

def get_nws_current(nws):

    obs = nws.get(
        "current",
        {}
    )

    temp_c = (
        obs
        .get("temperature", {})
        .get("value")
    )

    wind_ms = (
        obs
        .get("windSpeed", {})
        .get("value")
    )

    humidity = (
        obs
        .get("relativeHumidity", {})
        .get("value")
    )

    temp_f = None

    if temp_c is not None:
        temp_f = c_to_f(temp_c)

    wind_mph = None

    if wind_ms is not None:
        wind_mph = float(wind_ms) * 2.236936

    return {

        "temperatureF":
            round_temp(temp_f),

        "humidity":
            round_temp(humidity),

        "windMph":
            round_temp(wind_mph),

        "description":
            obs.get("textDescription"),

        "time":
            obs.get("timestamp"),

        "station":
            "KNYC"

    }


# =========================================================
# OPEN-METEO CURRENT
# =========================================================

def get_open_meteo_current(open_meteo):

    if not open_meteo:
        return None

    current = open_meteo.get(
        "current",
        {}
    )

    temperature = current.get(
        "temperature_2m"
    )

    humidity = current.get(
        "relative_humidity_2m"
    )

    wind = current.get(
        "wind_speed_10m"
    )

    return {

        "temperatureF":
            round_temp(temperature),

        "humidity":
            round_temp(humidity),

        "windMph":
            round_temp(wind),

        "time":
            current.get("time")

    }


# =========================================================
# WEATHERAPI CURRENT
# =========================================================

def get_weatherapi_current(weatherapi):

    if not weatherapi:
        return None

    current = weatherapi.get(
        "current",
        {}
    )

    return {

        "temperatureF":
            round_temp(
                current.get("temp_f")
            ),

        "humidity":
            round_temp(
                current.get("humidity")
            ),

        "windMph":
            round_temp(
                current.get("wind_mph")
            ),

        "description":
            (
                current
                .get("condition", {})
                .get("text")
            ),

        "time":
            current.get("last_updated")

    }


# =========================================================
# CURRENT CONSENSUS
# =========================================================

def build_current_consensus(
    nws_current,
    open_meteo_current,
    weatherapi_current
):

    sources = {}

    if (
        nws_current
        and nws_current.get("temperatureF") is not None
    ):

        sources["NWS"] = (
            nws_current["temperatureF"]
        )

    if (
        open_meteo_current
        and open_meteo_current.get("temperatureF")
        is not None
    ):

        sources["Open-Meteo"] = (
            open_meteo_current["temperatureF"]
        )

    if (
        weatherapi_current
        and weatherapi_current.get("temperatureF")
        is not None
    ):

        sources["WeatherAPI"] = (
            weatherapi_current["temperatureF"]
        )

    values = list(
        sources.values()
    )

    if not values:

        consensus = None

    else:

        # Median gives us the middle value
        # when the sources disagree.
        consensus = statistics.median(
            values
        )

    return {

        "temperatureF":
            round_temp(consensus),

        "sources":
            sources,

        "sourceCount":
            len(sources)

    }


# =========================================================
# PAST 6 HOURS
# =========================================================

def six_hour_extremes(nws):

    observations = []

    for feature in nws.get(
        "history",
        []
    ):

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
        key=lambda x:
            x["temperature"]
    )

    low = min(
        observations,
        key=lambda x:
            x["temperature"]
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

def build_forecast_consensus(
    nws,
    open_meteo,
    weatherapi
):

    hourly = {}

    # -----------------------------------------------------
    # NWS
    # -----------------------------------------------------

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

        if (
            timestamp is None
            or temperature is None
        ):
            continue

        try:

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
            )["NWS"] = float(
                temperature
            )

        except Exception:
            pass


    # -----------------------------------------------------
    # OPEN-METEO
    # -----------------------------------------------------

    if open_meteo:

        times = (
            open_meteo
            .get("hourly", {})
            .get("time", [])
        )

        temperatures = (
            open_meteo
            .get("hourly", {})
            .get(
                "temperature_2m",
                []
            )
        )

        eastern = ZoneInfo(
            TIMEZONE
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
                    temperature
                )

            except Exception:
                pass


    # -----------------------------------------------------
    # WEATHERAPI
    # -----------------------------------------------------

    if weatherapi:

        eastern = ZoneInfo(
            TIMEZONE
        )

        forecast_days = (
            weatherapi
            .get("forecast", {})
            .get("forecastday", [])
        )

        for day in forecast_days:

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
                        temperature
                    )

                except Exception:
                    pass


    # -----------------------------------------------------
    # MEDIAN CONSENSUS
    # -----------------------------------------------------

    result = []

    for timestamp, sources in hourly.items():

        if not sources:
            continue

        values = list(
            sources.values()
        )

        consensus = statistics.median(
            values
        )

        # NWS forecast description
        description = "Consensus"

        for period in nws.get(
            "forecast",
            []
        ):

            period_start = period.get(
                "startTime"
            )

            if not period_start:
                continue

            try:

                dt = datetime.fromisoformat(
                    period_start.replace(
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

                    description = period.get(
                        "shortForecast",
                        "Consensus"
                    )

                    break

            except Exception:
                pass

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
        key=lambda x:
            x["time"]
    )

    return result[:24]


# =========================================================
# WEATHER DATA
# =========================================================

def weather():

    errors = []


    # -----------------------------------------------------
    # NWS
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # OPEN-METEO
    # -----------------------------------------------------

    try:

        open_meteo = get_open_meteo()

    except Exception as e:

        open_meteo = None

        errors.append(
            "Open-Meteo: " + str(e)
        )


    # -----------------------------------------------------
    # WEATHERAPI
    # -----------------------------------------------------

    try:

        weatherapi = get_weatherapi()

    except Exception as e:

        weatherapi = None

        errors.append(
            "WeatherAPI: " + str(e)
        )


    # -----------------------------------------------------
    # CURRENT DATA
    # -----------------------------------------------------

    nws_current = get_nws_current(
        nws
    )

    open_meteo_current = (
        get_open_meteo_current(
            open_meteo
        )
    )

    weatherapi_current = (
        get_weatherapi_current(
            weatherapi
        )
    )


    current_consensus = (
        build_current_consensus(
            nws_current,
            open_meteo_current,
            weatherapi_current
        )
    )


    # -----------------------------------------------------
    # RESPONSE
    # -----------------------------------------------------

    return {

        "station":
            "KNYC",

        "location": {

            "name":
                "Central Park",

            "latitude":
                LAT,

            "longitude":
                LON,

            "timezone":
                TIMEZONE

        },

        "fetchedAt":
            time.time() * 1000,


        # -------------------------------------------------
        # CURRENT
        # -------------------------------------------------

        "current": {

            "consensus":
                current_consensus,

            "NWS":
                nws_current,

            "Open-Meteo":
                open_meteo_current,

            "WeatherAPI":
                weatherapi_current

        },


        # -------------------------------------------------
        # SIX HOUR
        # -------------------------------------------------

        "sixHour":
            six_hour_extremes(
                nws
            ),


        # -------------------------------------------------
        # FORECAST
        # -------------------------------------------------

        "forecast":
            build_forecast_consensus(
                nws,
                open_meteo,
                weatherapi
            ),


        # -------------------------------------------------
        # PROVIDERS
        # -------------------------------------------------

        "providers": {

            "NWS":
                bool(
                    nws.get("forecast")
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

    font-size: 58px;

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


/* CURRENT SOURCES */

.consensus-label {

    color: #888f99;

    font-size: 12px;

    letter-spacing: 1px;

    margin-top: 22px;

}

.consensus {

    font-size: 34px;

    font-weight: 700;

    margin-top: 4px;

}

.source-grid {

    display: grid;

    grid-template-columns:
        1fr 1fr 1fr;

    gap: 8px;

    margin-top: 15px;

}

.source-temp {

    background: #20242a;

    border-radius: 12px;

    padding: 11px;

}

.source-name {

    color: #858b95;

    font-size: 11px;

    margin-bottom: 5px;

}

.source-value {

    font-size: 20px;

    font-weight: 700;

}

.source-time {

    color: #707782;

    font-size: 10px;

    margin-top: 4px;

}


/* STATS */

.grid {

    display: grid;

    grid-template-columns:
        1fr 1fr;

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


/* PROVIDERS */

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


/* FORECAST */

.hour {

    padding: 14px 0;

    border-bottom:
        1px solid #292d34;

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


/* BUTTON */

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


/* ERROR */

.error {

    display: none;

    background: #351b1e;

    border: 1px solid #633137;

    color: #ffb9bf;

    padding: 13px;

    border-radius: 13px;

    margin-bottom: 15px;

}


/* MOBILE */

@media(max-width:500px) {

    .temperature {

        font-size: 52px;

    }

    .source-grid {

        grid-template-columns:
            1fr 1fr;

    }

    .hour-weather {

        font-size: 11px;

    }

}

</style>

</head>


<body>

<div class="container">


<h1>
Central Park Weather
</h1>


<div class="subtitle">
KNYC • Central Park, New York
</div>


<div id="error"
     class="error">
</div>


<!-- =====================================================
     CURRENT CONSENSUS
===================================================== -->

<div class="card current">

<div class="label">
CURRENT CONSENSUS TEMPERATURE
</div>


<div id="consensusTemp"
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


<div class="consensus-label">
SOURCE TEMPERATURES
</div>


<div id="currentSources"
     class="source-grid">

</div>


</div>


<!-- =====================================================
     CURRENT CONDITIONS
===================================================== -->

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


<!-- =====================================================
     SIX HOURS
===================================================== -->

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


<!-- =====================================================
     PROVIDERS
===================================================== -->

<div class="card">

<div class="title">
Forecast Sources
</div>


<div id="sources"
     class="sources">

Loading...

</div>

</div>


<!-- =====================================================
     FORECAST
===================================================== -->

<div class="card">

<div class="title">
Next 24 Hours
</div>


<div id="forecast">

<div style="
color:#777e88;
text-align:center;
padding:20px;
">

Loading forecast...

</div>

</div>

</div>


<button onclick="loadWeather()">
Refresh Weather
</button>


</div>


<script>


// =========================================================
// LOAD WEATHER
// =========================================================

async function loadWeather() {

    const error =
        document.getElementById(
            "error"
        );

    error.style.display =
        "none";


    try {

        const response =
            await fetch(
                "/api/weather?t=" +
                Date.now(),
                {
                    cache:
                        "no-store"
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


// =========================================================
// TIME
// =========================================================

function time(value) {

    if (!value)
        return "--";


    const d =
        new Date(value);


    if (isNaN(d.getTime()))
        return "--";


    return d.toLocaleTimeString(
        [],
        {
            hour:
                "numeric",

            minute:
                "2-digit"
        }
    );

}


// =========================================================
// TEMPERATURE
// =========================================================

function temp(value) {

    if (value == null)
        return "--.-°F";


    return Number(value)
        .toFixed(1)
        + "°F";

}


// =========================================================
// CURRENT SOURCE CARD
// =========================================================

function makeSourceCard(
    name,
    source
) {

    const div =
        document.createElement(
            "div"
        );


    div.className =
        "source-temp";


    let value =
        "--.-°F";


    if (
        source &&
        source.temperatureF != null
    ) {

        value =
            temp(
                source.temperatureF
            );

    }


    let sourceTime = "--";


    if (
        source &&
        source.time
    ) {

        sourceTime =
            time(
                source.time
            );

    }


    div.innerHTML = `

        <div class="source-name">
            ${name}
        </div>

        <div class="source-value">
            ${value}
        </div>

        <div class="source-time">
            ${sourceTime}
        </div>

    `;


    return div;

}


// =========================================================
// SHOW WEATHER
// =========================================================

function showWeather(data) {


    const current =
        data.current || {};


    const consensus =
        current.consensus || {};


    // -----------------------------------------------------
    // CONSENSUS
    // -----------------------------------------------------

    document.getElementById(
        "consensusTemp"
    ).textContent =
        temp(
            consensus.temperatureF
        );


    // -----------------------------------------------------
    // DESCRIPTION
    // -----------------------------------------------------

    let description =
        "Conditions unavailable";


    if (
        current.NWS &&
        current.NWS.description
    ) {

        description =
            current.NWS.description;

    } else if (
        current.WeatherAPI &&
        current.WeatherAPI.description
    ) {

        description =
            current.WeatherAPI.description;

    }


    document.getElementById(
        "description"
    ).textContent =
        description;


    // -----------------------------------------------------
    // UPDATED
    // -----------------------------------------------------

    document.getElementById(
        "updated"
    ).textContent =
        "Updated " +
        time(data.fetchedAt) +
        " • " +
        (
            consensus.sourceCount || 0
        ) +
        " sources";


    // -----------------------------------------------------
    // CURRENT SOURCES
    // -----------------------------------------------------

    const sourceBox =
        document.getElementById(
            "currentSources"
        );


    sourceBox.innerHTML =
        "";


    sourceBox.appendChild(
        makeSourceCard(
            "NWS",
            current.NWS
        )
    );


    sourceBox.appendChild(
        makeSourceCard(
            "Open-Meteo",
            current["Open-Meteo"]
        )
    );


    sourceBox.appendChild(
        makeSourceCard(
            "WeatherAPI",
            current.WeatherAPI
        )
    );


    // -----------------------------------------------------
    // HUMIDITY
    // -----------------------------------------------------

    let humidity = null;


    if (
        current.NWS &&
        current.NWS.humidity != null
    ) {

        humidity =
            current.NWS.humidity;

    } else if (
        current["Open-Meteo"] &&
        current["Open-Meteo"].humidity != null
    ) {

        humidity =
            current["Open-Meteo"].humidity;

    } else if (
        current.WeatherAPI &&
        current.WeatherAPI.humidity != null
    ) {

        humidity =
            current.WeatherAPI.humidity;

    }


    if (humidity != null) {

        document.getElementById(
            "humidity"
        ).textContent =
            Number(humidity)
            .toFixed(0) +
            "%";

    }


    // -----------------------------------------------------
    // WIND
    // -----------------------------------------------------

    let wind = null;


    if (
        current.NWS &&
        current.NWS.windMph != null
    ) {

        wind =
            current.NWS.windMph;

    } else if (
        current["Open-Meteo"] &&
        current["Open-Meteo"].windMph != null
    ) {

        wind =
            current["Open-Meteo"].windMph;

    } else if (
        current.WeatherAPI &&
        current.WeatherAPI.windMph != null
    ) {

        wind =
            current.WeatherAPI.windMph;

    }


    if (wind != null) {

        document.getElementById(
            "wind"
        ).textContent =
            Number(wind)
            .toFixed(1) +
            " mph";

    }


    // -----------------------------------------------------
    // SIX-HOUR HIGH
    // -----------------------------------------------------

    if (
        data.sixHour &&
        data.sixHour.high
    ) {

        document.getElementById(
            "high"
        ).textContent =
            temp(
                data.sixHour.high.temperature
            );


        document.getElementById(
            "highTime"
        ).textContent =
            time(
                data.sixHour.high.time
            );

    }


    // -----------------------------------------------------
    // SIX-HOUR LOW
    // -----------------------------------------------------

    if (
        data.sixHour &&
        data.sixHour.low
    ) {

        document.getElementById(
            "low"
        ).textContent =
            temp(
                data.sixHour.low.temperature
            );


        document.getElementById(
            "lowTime"
        ).textContent =
            time(
                data.sixHour.low.time
            );

    }


    // -----------------------------------------------------
    // PROVIDERS
    // -----------------------------------------------------

    const providers =
        document.getElementById(
            "sources"
        );


    providers.innerHTML =
        "";


    let providerCount = 0;


    Object.entries(
        data.providers || {}
    ).forEach(
        ([name, active]) => {


            if (!active)
                return;


            providerCount++;


            const span =
                document.createElement(
                    "span"
                );


            span.className =
                "source";


            span.textContent =
                "✓ " + name;


            providers.appendChild(
                span
            );

        }
    );


    if (providerCount === 0) {

        providers.textContent =
            "No forecast providers available";

    }


    // -----------------------------------------------------
    // FORECAST
    // -----------------------------------------------------

    const forecastBox =
        document.getElementById(
            "forecast"
        );


    forecastBox.innerHTML =
        "";


    (
        data.forecast || []
    )
    .slice(0, 24)
    .forEach(
        p => {


            const row =
                document.createElement(
                    "div"
                );


            row.className =
                "hour";


            let providerValues =
                "";


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
                    .join(
                        " • "
                    );

            }


            row.innerHTML = `

                <div class="hour-main">

                    <div class="hour-time">
                        ${time(p.time)}
                    </div>

                    <div class="hour-temp">
                        ${temp(p.temperature)}
                    </div>

                    <div class="hour-weather">
                        ${p.shortForecast || "Consensus"}
                    </div>

                    <div class="hour-count">
                        ${p.sourceCount || 0}
                        source${p.sourceCount == 1 ? "" : "s"}
                    </div>

                </div>

                <div class="provider-values">
                    ${providerValues}
                </div>

            `;


            forecastBox.appendChild(
                row
            );

        }
    );

}


// =========================================================
// INITIAL LOAD
// =========================================================

loadWeather();


// =========================================================
// AUTO REFRESH — EVERY 5 MINUTES
// =========================================================

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


                self.send_response(
                    200
                )


                self.send_header(
                    "Content-Type",
                    "application/json"
                )


            else:


                data = HTML.encode(
                    "utf-8"
                )


                self.send_response(
                    200
                )


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


            self.wfile.write(
                data
            )


        except Exception as e:


            data = json.dumps({

                "error":
                    str(e)

            }).encode()


            self.send_response(
                500
            )


            self.send_header(
                "Content-Type",
                "application/json"
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


# =========================================================
# START SERVER
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
