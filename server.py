from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlparse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import statistics
import time


# =========================================================
# CONFIGURATION
# =========================================================

LAT = 40.78
LON = -73.97

STATION = "KNYC"
LOCATION_NAME = "Central Park, New York"

TZ = ZoneInfo("America/New_York")

UA = "CentralParkWeather/5.0"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

NWS_POINT_URL = (
    f"https://api.weather.gov/points/{LAT},{LON}"
)


# =========================================================
# HTTP
# =========================================================

def get_json(url):

    req = Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/json"
        }
    )

    with urlopen(req, timeout=25) as response:

        return json.loads(
            response.read()
        )


# =========================================================
# TEMPERATURE HELPERS
# =========================================================

def round_temp(value):

    if value is None:
        return None

    return round(
        float(value),
        1
    )


def c_to_f(value):

    if value is None:
        return None

    return float(value) * 9 / 5 + 32


# =========================================================
# TIME HELPERS
# =========================================================

def parse_iso(value):

    if not value:
        return None

    try:

        return datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00"
            )
        )

    except Exception:

        return None


def hour_key(dt):

    return dt.astimezone(
        timezone.utc
    ).strftime(
        "%Y-%m-%dT%H:00:00Z"
    )


def local_hour_key(dt):

    return dt.astimezone(
        TZ
    ).strftime(
        "%Y-%m-%d %H:00"
    )


# =========================================================
# NWS / KNYC ACTUAL OBSERVATION
# =========================================================

def get_nws():

    point = get_json(
        NWS_POINT_URL
    )

    properties = point["properties"]

    forecast_url = properties[
        "forecastHourly"
    ]

    observation_stations_url = properties[
        "observationStations"
    ]

    # -----------------------------------------
    # Find KNYC
    # -----------------------------------------

    stations = get_json(
        observation_stations_url
    )

    station_url = None

    for feature in stations.get(
        "features",
        []
    ):

        station_properties = (
            feature.get(
                "properties",
                {}
            )
        )

        if (
            station_properties.get(
                "stationIdentifier"
            )
            == STATION
        ):

            station_url = feature.get(
                "id"
            )

            break

    if not station_url:

        raise Exception(
            "KNYC station not found"
        )

    # -----------------------------------------
    # Latest actual observation
    # -----------------------------------------

    latest = get_json(
        station_url +
        "/observations/latest"
    )

    actual = latest.get(
        "properties",
        {}
    )

    # -----------------------------------------
    # Previous 6 hours
    # -----------------------------------------

    now = datetime.now(
        timezone.utc
    )

    start = now - timedelta(
        hours=6
    )

    params = urlencode({

        "start":
            start.isoformat(),

        "end":
            now.isoformat()

    })

    history = get_json(
        station_url +
        "/observations?" +
        params
    )

    # -----------------------------------------
    # Hourly NWS forecast
    # -----------------------------------------

    forecast = get_json(
        forecast_url
    )

    return {

        "actual":
            actual,

        "history":
            history.get(
                "features",
                []
            ),

        "forecast":
            forecast
            .get(
                "properties",
                {}
            )
            .get(
                "periods",
                []
            )

    }


# =========================================================
# ACTUAL KNYC CONDITIONS
# =========================================================

def get_actual_conditions(nws):

    obs = nws.get(
        "actual",
        {}
    )

    temperature = (
        obs
        .get(
            "temperature",
            {}
        )
        .get(
            "value"
        )
    )

    humidity = (
        obs
        .get(
            "relativeHumidity",
            {}
        )
        .get(
            "value"
        )
    )

    wind = (
        obs
        .get(
            "windSpeed",
            {}
        )
        .get(
            "value"
        )
    )

    # NWS temperature is Celsius

    temperature = c_to_f(
        temperature
    )

    # NWS wind is km/h

    if wind is not None:

        wind = (
            float(wind)
            * 0.621371
        )

    return {

        "temperatureF":
            round_temp(
                temperature
            ),

        "humidity":
            round_temp(
                humidity
            ),

        "windMph":
            round_temp(
                wind
            ),

        "description":
            obs.get(
                "textDescription"
            ),

        "timestamp":
            obs.get(
                "timestamp"
            ),

        "station":
            STATION

    }


# =========================================================
# PAST 6 HOURS
# =========================================================

def get_six_hour_extremes(nws):

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
            .get(
                "temperature",
                {}
            )
            .get(
                "value"
            )
        )

        timestamp = props.get(
            "timestamp"
        )

        if (
            value is None
            or timestamp is None
        ):

            continue

        observations.append({

            "temperature":
                c_to_f(value),

            "timestamp":
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

            "timestamp":
                high["timestamp"]

        },

        "low": {

            "temperature":
                round_temp(
                    low["temperature"]
                ),

            "timestamp":
                low["timestamp"]

        }

    }


# =========================================================
# OPEN-METEO MODEL REQUEST
# =========================================================

def get_model(
    model_name,
    display_name,
    forecast_days=2
):

    params = urlencode({

        "latitude":
            LAT,

        "longitude":
            LON,

        "hourly":
            "temperature_2m",

        "temperature_unit":
            "fahrenheit",

        "timezone":
            "UTC",

        "forecast_days":
            forecast_days,

        "models":
            model_name

    })

    url = (
        OPEN_METEO_URL +
        "?" +
        params
    )

    data = get_json(
        url
    )

    hourly = data.get(
        "hourly",
        {}
    )

    times = hourly.get(
        "time",
        []
    )

    temperatures = hourly.get(
        "temperature_2m",
        []
    )

    result = []

    for timestamp, temperature in zip(
        times,
        temperatures
    ):

        if temperature is None:
            continue

        try:

            dt = datetime.fromisoformat(
                timestamp
            )

            # Open-Meteo is requested in UTC
            # so this is already an absolute time.

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            result.append({

                "time":
                    hour_key(dt),

                "temperature":
                    round_temp(
                        temperature
                    )

            })

        except Exception:
            continue

    return {

        "name":
            display_name,

        "model":
            model_name,

        "data":
            result

    }


# =========================================================
# ALL MODELS
# =========================================================

def get_all_models():

    models = {

        # ECMWF
        "ECMWF IFS":
            "ecmwf_ifs025",

        "ECMWF AIFS":
            "ecmwf_aifs025",

        # NOAA
        "GFS":
            "gfs_seamless",

        "HRRR":
            "hrrr",

        "NBM":
            "nbm_conus",

        "NAM":
            "nam_conus"

    }

    results = {}

    errors = []

    for display_name, model_name in models.items():

        try:

            results[display_name] = get_model(
                model_name,
                display_name
            )

        except Exception as e:

            errors.append(
                display_name +
                ": " +
                str(e)
            )

    return results, errors


# =========================================================
# MODEL ALIGNMENT
# =========================================================

def align_models(
    model_results
):

    aligned = {}

    for model_name, model in (
        model_results.items()
    ):

        for point in model.get(
            "data",
            []
        ):

            timestamp = point.get(
                "time"
            )

            temperature = point.get(
                "temperature"
            )

            if (
                timestamp is None
                or temperature is None
            ):

                continue

            aligned.setdefault(
                timestamp,
                {}
            )[model_name] = (
                temperature
            )

    return aligned


# =========================================================
# CONSENSUS
# =========================================================

def calculate_consensus(
    aligned
):

    forecast = []

    for timestamp, sources in aligned.items():

        values = list(
            sources.values()
        )

        if not values:
            continue

        # Median of the six models.
        # Actual KNYC observation is NOT included.

        consensus = statistics.median(
            values
        )

        forecast.append({

            "time":
                timestamp,

            "consensus":
                round_temp(
                    consensus
                ),

            "sources": {

                name:
                    round_temp(value)

                for name, value
                in sources.items()

            },

            "sourceCount":
                len(sources)

        })

    forecast.sort(
        key=lambda x:
            x["time"]
    )

    return forecast[:48]


# =========================================================
# FIND CURRENT MODEL TEMPERATURE
# =========================================================

def current_model_values(
    model_results
):

    now = datetime.now(
        timezone.utc
    )

    current_hour = now.replace(
        minute=0,
        second=0,
        microsecond=0
    )

    target = hour_key(
        current_hour
    )

    values = {}

    for model_name, model in (
        model_results.items()
    ):

        best = None
        best_difference = None

        for point in model.get(
            "data",
            []
        ):

            dt = parse_iso(
                point.get("time")
            )

            if dt is None:
                continue

            difference = abs(
                (
                    dt -
                    current_hour
                ).total_seconds()
            )

            # Only accept a model hour
            # within 90 minutes.

            if difference > 5400:
                continue

            if (
                best_difference is None
                or difference <
                best_difference
            ):

                best_difference = (
                    difference
                )

                best = point.get(
                    "temperature"
                )

        if best is not None:

            values[model_name] = (
                round_temp(best)
            )

    return {

        "timestamp":
            target,

        "models":
            values

    }


# =========================================================
# MODEL ERROR VS ACTUAL
# =========================================================

def calculate_current_errors(
    model_values,
    actual_temperature
):

    if actual_temperature is None:

        return {}

    result = {}

    for name, value in (
        model_values.items()
    ):

        if value is None:
            continue

        result[name] = {

            "forecast":
                round_temp(value),

            "actual":
                round_temp(
                    actual_temperature
                ),

            "error":
                round_temp(
                    value -
                    actual_temperature
                ),

            "absoluteError":
                round_temp(
                    abs(
                        value -
                        actual_temperature
                    )
                )

        }

    return result


# =========================================================
# NWS FORECAST DESCRIPTION
# =========================================================

def get_nws_descriptions(
    nws
):

    descriptions = {}

    for period in nws.get(
        "forecast",
        []
    ):

        timestamp = period.get(
            "startTime"
        )

        if not timestamp:
            continue

        dt = parse_iso(
            timestamp
        )

        if dt is None:
            continue

        descriptions[
            hour_key(dt)
        ] = period.get(
            "shortForecast",
            ""
        )

    return descriptions


# =========================================================
# WEATHER ENGINE
# =========================================================

def build_weather():

    errors = []

    # -----------------------------------------
    # NWS / KNYC
    # -----------------------------------------

    try:

        nws = get_nws()

    except Exception as e:

        nws = {

            "actual": {},
            "history": [],
            "forecast": []

        }

        errors.append(
            "NWS: " +
            str(e)
        )

    # -----------------------------------------
    # Models
    # -----------------------------------------

    model_results, model_errors = (
        get_all_models()
    )

    errors.extend(
        model_errors
    )

    # -----------------------------------------
    # Align
    # -----------------------------------------

    aligned = align_models(
        model_results
    )

    consensus = calculate_consensus(
        aligned
    )

    # -----------------------------------------
    # Actual observation
    # -----------------------------------------

    actual = get_actual_conditions(
        nws
    )

    actual_temperature = actual.get(
        "temperatureF"
    )

    # -----------------------------------------
    # Current model temperatures
    # -----------------------------------------

    current_models = (
        current_model_values(
            model_results
        )
    )

    current_model_temps = (
        current_models["models"]
    )

    # -----------------------------------------
    # Current model consensus
    # -----------------------------------------

    current_values = list(
        current_model_temps.values()
    )

    if current_values:

        current_consensus = (
            round_temp(
                statistics.median(
                    current_values
                )
            )
        )

    else:

        current_consensus = None

    # -----------------------------------------
    # Current model errors
    # -----------------------------------------

    current_errors = (
        calculate_current_errors(
            current_model_temps,
            actual_temperature
        )
    )

    # -----------------------------------------
    # NWS descriptions
    # -----------------------------------------

    descriptions = (
        get_nws_descriptions(
            nws
        )
    )

    for point in consensus:

        point["description"] = (
            descriptions.get(
                point["time"],
                "Model forecast"
            )
        )

    # -----------------------------------------
    # Providers / models
    # -----------------------------------------

    providers = {}

    for name in (
        "ECMWF IFS",
        "ECMWF AIFS",
        "GFS",
        "HRRR",
        "NBM",
        "NAM"
    ):

        providers[name] = (
            name in model_results
        )

    providers["KNYC Actual"] = (
        actual_temperature is not None
    )

    # -----------------------------------------
    # Final result
    # -----------------------------------------

    return {

        "station":
            STATION,

        "location":
            LOCATION_NAME,

        "coordinates": {

            "latitude":
                LAT,

            "longitude":
                LON

        },

        "fetchedAt":
            time.time() * 1000,

        "actual":
            actual,

        "sixHour":
            get_six_hour_extremes(
                nws
            ),

        "currentModels": {

            "timestamp":
                current_models[
                    "timestamp"
                ],

            "temperatures":
                current_model_temps,

            "consensus":
                current_consensus,

            "actual":
                actual_temperature,

            "errors":
                current_errors

        },

        "forecast":
            consensus,

        "providers":
            providers,

        "modelCount":
            len(model_results),

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

<title>
Central Park Weather
</title>

<style>

* {
    box-sizing: border-box;
}

body {

    margin: 0;

    background:
        #0d0f12;

    color:
        white;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Arial,
        sans-serif;
}

.container {

    max-width:
        760px;

    margin:
        auto;

    padding:
        16px;
}

h1 {

    margin:
        5px 0;

    font-size:
        29px;
}

.subtitle {

    color:
        #858b95;

    margin-bottom:
        18px;
}

.card {

    background:
        #171a1f;

    border:
        1px solid #292d34;

    border-radius:
        18px;

    padding:
        18px;

    margin-bottom:
        15px;
}

.title {

    font-size:
        20px;

    font-weight:
        700;

    margin-bottom:
        15px;
}

.current {

    text-align:
        center;

    padding:
        25px 15px;
}

.label {

    color:
        #888f99;

    font-size:
        12px;

    letter-spacing:
        1px;
}

.temperature {

    font-size:
        62px;

    font-weight:
        700;

    margin:
        8px 0;
}

.description {

    color:
        #c5cad1;

    font-size:
        18px;
}

.updated {

    color:
        #707782;

    font-size:
        12px;

    margin-top:
        8px;
}

.consensus {

    text-align:
        center;

    background:
        #20242a;

    border-radius:
        16px;

    padding:
        18px;

    margin-bottom:
        14px;
}

.consensus-number {

    font-size:
        48px;

    font-weight:
        700;
}

.consensus-label {

    color:
        #9299a4;

    font-size:
        12px;

    letter-spacing:
        1px;
}

.actual {

    text-align:
        center;

    padding:
        15px;

    border-radius:
        14px;

    background:
        #20242a;
}

.actual-number {

    font-size:
        34px;

    font-weight:
        700;
}

.model-grid {

    display:
        grid;

    grid-template-columns:
        1fr 1fr;

    gap:
        10px;
}

.model {

    background:
        #20242a;

    border-radius:
        14px;

    padding:
        14px;
}

.model-name {

    color:
        #aeb4bd;

    font-size:
        13px;

    margin-bottom:
        5px;
}

.model-temp {

    font-size:
        25px;

    font-weight:
        700;
}

.model-error {

    color:
        #777f89;

    font-size:
        11px;

    margin-top:
        5px;
}

.source-list {

    display:
        flex;

    flex-wrap:
        wrap;

    gap:
        7px;
}

.source {

    background:
        #20242a;

    border:
        1px solid #30353d;

    border-radius:
        9px;

    padding:
        7px 10px;

    color:
        #cbd0d7;

    font-size:
        12px;
}

.hour {

    padding:
        14px 0;

    border-bottom:
        1px solid #292d34;
}

.hour:last-child {

    border-bottom:
        0;
}

.hour-main {

    display:
        grid;

    grid-template-columns:
        23% 22% 35% 20%;

    align-items:
        center;
}

.hour-time {

    font-weight:
        600;

    color:
        #c8ccd3;
}

.hour-temp {

    font-size:
        19px;

    font-weight:
        700;
}

.hour-weather {

    color:
        #aeb4bd;

    font-size:
        13px;
}

.hour-count {

    text-align:
        right;

    color:
        #70b8ff;

    font-size:
        11px;
}

.provider-values {

    margin-top:
        7px;

    color:
        #737a85;

    font-size:
        11px;

    line-height:
        1.6;
}

.stat-grid {

    display:
        grid;

    grid-template-columns:
        1fr 1fr;

    gap:
        12px;
}

.stat {

    background:
        #20242a;

    border-radius:
        14px;

    padding:
        15px;
}

.stat-value {

    font-size:
        25px;

    font-weight:
        700;
}

.stat-time {

    color:
        #777e88;

    font-size:
        13px;

    margin-top:
        5px;
}

button {

    width:
        100%;

    border:
        0;

    border-radius:
        13px;

    padding:
        14px;

    background:
        white;

    color:
        #111;

    font-size:
        15px;

    font-weight:
        700;
}

.error {

    display:
        none;

    background:
        #351b1e;

    border:
        1px solid #633137;

    color:
        #ffb9bf;

    padding:
        13px;

    border-radius:
        13px;

    margin-bottom:
        15px;
}

@media(max-width:500px) {

    .temperature {

        font-size:
            55px;
    }

    .hour-main {

        grid-template-columns:
            23% 22% 35% 20%;
    }

    .hour-weather {

        font-size:
            11px;
    }

    .model-grid {

        grid-template-columns:
            1fr 1fr;
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


<!-- ================================================= -->
<!-- MODEL CONSENSUS -->
<!-- ================================================= -->

<div class="card">

<div class="title">
Model Consensus
</div>


<div class="consensus">

<div class="consensus-label">
SIX-MODEL TEMPERATURE CONSENSUS
</div>

<div id="consensus"
     class="consensus-number">
--.-°F
</div>

</div>


<div class="actual">

<div class="consensus-label">
ACTUAL KNYC OBSERVATION
</div>

<div id="actual"
     class="actual-number">
--.-°F
</div>

<div id="actualTime"
     class="stat-time">
--
</div>

</div>

</div>


<!-- ================================================= -->
<!-- SIX MODELS -->
<!-- ================================================= -->

<div class="card">

<div class="title">
Current Model Temperatures
</div>

<div id="models"
     class="model-grid">

</div>

</div>


<!-- ================================================= -->
<!-- CURRENT CONDITIONS -->
<!-- ================================================= -->

<div class="card">

<div class="title">
Actual KNYC Conditions
</div>

<div class="stat-grid">

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


<!-- ================================================= -->
<!-- PAST SIX HOURS -->
<!-- ================================================= -->

<div class="card">

<div class="title">
Past 6 Hours — KNYC
</div>

<div class="stat-grid">

<div class="stat">

<div class="label">
PEAK
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
LOWEST
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


<!-- ================================================= -->
<!-- SOURCES -->
<!-- ================================================= -->

<div class="card">

<div class="title">
Models Available
</div>

<div id="sources"
     class="source-list">

</div>

</div>


<!-- ================================================= -->
<!-- NEXT 24 HOURS -->
<!-- ================================================= -->

<div class="card">

<div class="title">
Next 24 Hours
</div>

<div id="forecast">

Loading...

</div>

</div>


<button onclick="loadWeather()">
Refresh Weather
</button>


</div>


<script>


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

    }

    catch (e) {

        console.error(e);

        error.textContent =
            "Weather update failed: " +
            e.message;

        error.style.display =
            "block";
    }
}


function formatTime(
    value
) {

    if (!value)
        return "--";

    const date =
        new Date(value);

    if (
        isNaN(
            date.getTime()
        )
    )
        return "--";

    return date.toLocaleTimeString(
        [],
        {
            hour:
                "numeric",

            minute:
                "2-digit"
        }
    );
}


function formatTemp(
    value
) {

    if (
        value === null ||
        value === undefined
    )
        return "--.-°F";

    return (
        Number(value)
        .toFixed(1)
        +
        "°F"
    );
}


function showWeather(
    data
) {

    const actual =
        data.actual || {};

    const currentModels =
        data.currentModels || {};


    // ==========================================
    // CONSENSUS
    // ==========================================

    document.getElementById(
        "consensus"
    ).textContent =
        formatTemp(
            currentModels.consensus
        );


    // ==========================================
    // ACTUAL KNYC
    // ==========================================

    document.getElementById(
        "actual"
    ).textContent =
        formatTemp(
            currentModels.actual
        );

    document.getElementById(
        "actualTime"
    ).textContent =
        "Observed " +
        formatTime(
            actual.timestamp
        );


    // ==========================================
    // HUMIDITY
    // ==========================================

    if (
        actual.humidity !== null &&
        actual.humidity !== undefined
    ) {

        document.getElementById(
            "humidity"
        ).textContent =
            Number(
                actual.humidity
            ).toFixed(0) +
            "%";
    }


    // ==========================================
    // WIND
    // ==========================================

    if (
        actual.windMph !== null &&
        actual.windMph !== undefined
    ) {

        document.getElementById(
            "wind"
        ).textContent =
            Number(
                actual.windMph
            ).toFixed(1) +
            " mph";
    }


    // ==========================================
    // MODELS
    // ==========================================

    const modelBox =
        document.getElementById(
            "models"
        );

    modelBox.innerHTML = "";


    const modelTemps =
        currentModels.temperatures || {};

    const modelErrors =
        currentModels.errors || {};


    Object.entries(
        modelTemps
    ).forEach(
        ([name, temperature]) => {

            const div =
                document.createElement(
                    "div"
                );

            div.className =
                "model";


            let errorText = "";

            if (
                modelErrors[name]
            ) {

                const error =
                    modelErrors[name].error;

                if (error > 0) {

                    errorText =
                        "+" +
                        error.toFixed(1) +
                        "°F vs actual";

                }
                else {

                    errorText =
                        error.toFixed(1) +
                        "°F vs actual";
                }
            }


            div.innerHTML = `

<div class="model-name">
${name}
</div>

<div class="model-temp">
${formatTemp(temperature)}
</div>

<div class="model-error">
${errorText}
</div>

`;

            modelBox.appendChild(
                div
            );

        }
    );


    // ==========================================
    // SOURCES
    // ==========================================

    const sourceBox =
        document.getElementById(
            "sources"
        );

    sourceBox.innerHTML = "";


    Object.entries(
        data.providers || {}
    ).forEach(
        ([name, active]) => {

            if (!active)
                return;

            const span =
                document.createElement(
                    "span"
                );

            span.className =
                "source";

            if (
                name ===
                "KNYC Actual"
            ) {

                span.textContent =
                    "✓ " + name;

            }
            else {

                span.textContent =
                    "✓ " + name;
            }

            sourceBox.appendChild(
                span
            );

        }
    );


    // ==========================================
    // SIX HOUR
    // ==========================================

    if (
        data.sixHour &&
        data.sixHour.high
    ) {

        document.getElementById(
            "high"
        ).textContent =
            formatTemp(
                data.sixHour.high.temperature
            );

        document.getElementById(
            "highTime"
        ).textContent =
            formatTime(
                data.sixHour.high.timestamp
            );
    }


    if (
        data.sixHour &&
        data.sixHour.low
    ) {

        document.getElementById(
            "low"
        ).textContent =
            formatTemp(
                data.sixHour.low.temperature
            );

        document.getElementById(
            "lowTime"
        ).textContent =
            formatTime(
                data.sixHour.low.timestamp
            );
    }


    // ==========================================
    // FORECAST
    // ==========================================

    const forecastBox =
        document.getElementById(
            "forecast"
        );

    forecastBox.innerHTML = "";


    (
        data.forecast || []
    )
    .slice(
        0,
        24
    )
    .forEach(
        point => {

            const row =
                document.createElement(
                    "div"
                );

            row.className =
                "hour";


            let values = "";

            if (
                point.sources
            ) {

                values =
                    Object.entries(
                        point.sources
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
${formatTime(point.time)}
</div>

<div class="hour-temp">
${formatTemp(point.consensus)}
</div>

<div class="hour-weather">
${point.description || ""}
</div>

<div class="hour-count">
${point.sourceCount}
models
</div>

</div>

<div class="provider-values">
${values}
</div>

`;

            forecastBox.appendChild(
                row
            );

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

class Handler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        try:

            path =
                urlparse(
                    self.path
                ).path

            # ---------------------------------
            # API
            # ---------------------------------

            if path == "/api/weather":

                data =
                    json.dumps(
                        build_weather()
                    ).encode(
                        "utf-8"
                    )

                self.send_response(
                    200
                )

                self.send_header(
                    "Content-Type",
                    "application/json"
                )

            # ---------------------------------
            # WEBSITE
            # ---------------------------------

            else:

                data =
                    HTML.encode(
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

            self.send_header(
                "Expires",
                "0"
            )

            self.end_headers()

            self.wfile.write(
                data
            )

        except Exception as e:

            print(
                "SERVER ERROR:",
                e
            )

            data =
                json.dumps({
                    "error":
                        str(e)
                }).encode(
                    "utf-8"
                )

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

PORT = int(
    os.environ.get(
        "PORT",
        "10000"
    )
)

print(
    "Central Park Weather running on port",
    PORT
)

server =
    ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT
        ),
        Handler
    )

server.serve_forever()
