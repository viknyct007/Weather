from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import statistics


# ============================================================
# CENTRAL PARK / KNYC WEATHER MODEL CONSENSUS
# ============================================================

LAT = 40.7812
LON = -73.9665

TZ = ZoneInfo("America/New_York")

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "10000"))

USER_AGENT = "CentralParkWeatherApp/7.0"

NWS_STATION = "KNYC"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


# ============================================================
# WEATHER MODELS
#
# These are Open-Meteo's documented model IDs.
# ============================================================

MODELS = {
    "ECMWF IFS": "ecmwf_ifs",
    "ECMWF AIFS": "ecmwf_aifs025_single",
    "NBM": "ncep_nbm_conus",
    "NAM": "ncep_nam_conus",
    "HRRR": "ncep_hrrr_conus",
    "GFS": "ncep_gfs_global",
}


# ============================================================
# HTTP
# ============================================================

def get_json(url, timeout=25):

    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=timeout) as response:

        raw = response.read().decode("utf-8")

        return json.loads(raw)


# ============================================================
# TEMPERATURE HELPERS
# ============================================================

def clean_temp(value):

    if value is None:
        return None

    try:

        value = float(value)

        if value != value:
            return None

        return round(value, 1)

    except Exception:

        return None


def median(values):

    values = [
        float(value)
        for value in values
        if value is not None
    ]

    if not values:
        return None

    return round(
        statistics.median(values),
        1
    )


def parse_datetime(value):

    if not value:
        return None

    try:

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:

        return None


# ============================================================
# KNYC CURRENT OBSERVATION
# ============================================================

def get_knyc_observation():

    url = (
        "https://api.weather.gov/stations/"
        + NWS_STATION
        + "/observations/latest"
    )

    try:

        data = get_json(url)

        props = data.get(
            "properties",
            {}
        )

        temp_c = (
            props
            .get("temperature", {})
            .get("value")
        )

        if temp_c is not None:

            temp_f = (
                temp_c * 9 / 5
            ) + 32

        else:

            temp_f = None


        humidity = (
            props
            .get("relativeHumidity", {})
            .get("value")
        )


        wind_mps = (
            props
            .get("windSpeed", {})
            .get("value")
        )

        if wind_mps is not None:

            wind_mph = (
                wind_mps * 2.236936
            )

        else:

            wind_mph = None


        return {

            "temperature": clean_temp(
                temp_f
            ),

            "humidity": (
                round(humidity, 1)
                if humidity is not None
                else None
            ),

            "wind_mph": (
                round(wind_mph, 1)
                if wind_mph is not None
                else None
            ),

            "description":
                props.get(
                    "textDescription"
                ),

            "timestamp":
                props.get(
                    "timestamp"
                ),

            "station":
                NWS_STATION,
        }


    except Exception as error:

        print(
            "KNYC observation error:",
            error
        )

        return {

            "temperature": None,

            "humidity": None,

            "wind_mph": None,

            "description": None,

            "timestamp": None,

            "station":
                NWS_STATION,
        }


# ============================================================
# KNYC PAST 6 HOURS
# ============================================================

def get_knyc_history():

    now = datetime.now(
        timezone.utc
    )

    start = (
        now -
        timedelta(hours=6)
    )

    params = urlencode({

        "start":
            start.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),

        "end":
            now.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),

        "limit": "100",
    })


    url = (
        "https://api.weather.gov/stations/"
        + NWS_STATION
        + "/observations?"
        + params
    )


    try:

        data = get_json(url)

        temperatures = []


        for feature in data.get(
            "features",
            []
        ):

            props = feature.get(
                "properties",
                {}
            )

            temp_c = (
                props
                .get("temperature", {})
                .get("value")
            )

            if temp_c is None:
                continue


            temp_f = (
                temp_c * 9 / 5
            ) + 32


            temperatures.append(
                round(temp_f, 1)
            )


        if not temperatures:

            return {
                "high": None,
                "low": None,
            }


        return {

            "high":
                max(temperatures),

            "low":
                min(temperatures),
        }


    except Exception as error:

        print(
            "KNYC history error:",
            error
        )

        return {

            "high": None,

            "low": None,
        }


# ============================================================
# FETCH ONE MODEL
# ============================================================

def get_model_forecast(model_id):

    params = {

        "latitude":
            str(LAT),

        "longitude":
            str(LON),

        "hourly":
            "temperature_2m",

        "temperature_unit":
            "fahrenheit",

        "timezone":
            "UTC",

        "forecast_days":
            "3",

        "models":
            model_id,
    }


    url = (
        OPEN_METEO_URL
        + "?"
        + urlencode(params)
    )


    try:

        data = get_json(url)

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


        result = {}


        for timestamp, temperature in zip(
            times,
            temperatures
        ):

            dt = parse_datetime(
                timestamp
            )

            if dt is None:
                continue


            key = dt.strftime(
                "%Y-%m-%dT%H:00:00Z"
            )


            result[key] = clean_temp(
                temperature
            )


        print(
            model_id,
            "returned",
            len(result),
            "hourly values"
        )


        return result


    except Exception as error:

        print(
            "Model error:",
            model_id,
            error
        )

        return {}


# ============================================================
# BUILD DAILY PEAKS
# ============================================================

def build_daily_peaks(forecast):

    days = {}


    for hour in forecast:

        dt = parse_datetime(
            hour["time"]
        )

        if dt is None:
            continue


        local_dt = dt.astimezone(
            TZ
        )


        date_key = local_dt.strftime(
            "%Y-%m-%d"
        )


        if date_key not in days:

            days[date_key] = {

                "date":
                    date_key,

                "displayDate":
                    local_dt.strftime(
                        "%A, %B %-d"
                    ),

                "models": {},
            }


        for model_name in MODELS:

            temperature = (
                hour["models"]
                .get(model_name)
            )


            if temperature is None:
                continue


            if model_name not in (
                days[date_key]["models"]
            ):

                days[date_key][
                    "models"
                ][model_name] = []


            days[date_key][
                "models"
            ][model_name].append({

                "temperature":
                    temperature,

                "time":
                    hour["localTime"],
            })


    results = []


    for date_key in sorted(
        days.keys()
    ):

        day = days[date_key]

        model_peaks = {}


        for model_name in MODELS:

            values = (
                day["models"]
                .get(
                    model_name,
                    []
                )
            )


            if not values:

                model_peaks[
                    model_name
                ] = {

                    "temperature":
                        None,

                    "time":
                        None,
                }

                continue


            peak = max(
                values,
                key=lambda item:
                    item["temperature"]
            )


            model_peaks[
                model_name
            ] = {

                "temperature":
                    clean_temp(
                        peak["temperature"]
                    ),

                "time":
                    peak["time"],
            }


        peak_values = [

            value["temperature"]

            for value
            in model_peaks.values()

            if value["temperature"]
            is not None
        ]


        consensus = median(
            peak_values
        )


        # Find the model whose predicted
        # peak is closest to the consensus.
        consensus_time = None


        if (
            consensus is not None
            and model_peaks
        ):

            valid_peaks = [

                value

                for value
                in model_peaks.values()

                if (
                    value["temperature"]
                    is not None
                    and
                    value["time"]
                    is not None
                )
            ]


            if valid_peaks:

                closest = min(

                    valid_peaks,

                    key=lambda item:
                        abs(
                            item["temperature"]
                            -
                            consensus
                        )
                )


                consensus_time = (
                    closest["time"]
                )


        results.append({

            "date":
                date_key,

            "displayDate":
                day["displayDate"],

            "models":
                model_peaks,

            "consensus":
                consensus,

            "consensusTime":
                consensus_time,

            "modelCount":
                len(peak_values),
        })


    return results


# ============================================================
# MAIN WEATHER FUNCTION
# ============================================================

def get_weather():

    now = datetime.now(
        timezone.utc
    )


    current_hour = now.replace(

        minute=0,

        second=0,

        microsecond=0,
    )


    # --------------------------------------------------------
    # KNYC actual
    # --------------------------------------------------------

    actual = get_knyc_observation()

    history = get_knyc_history()


    # --------------------------------------------------------
    # Download all six models
    # --------------------------------------------------------

    model_data = {}


    for model_name, model_id in MODELS.items():

        print(
            "Fetching:",
            model_name
        )

        model_data[
            model_name
        ] = get_model_forecast(
            model_id
        )


    # --------------------------------------------------------
    # Build 72 aligned hours
    # --------------------------------------------------------

    forecast = []


    for i in range(72):

        dt = (
            current_hour
            +
            timedelta(hours=i)
        )


        key = dt.strftime(
            "%Y-%m-%dT%H:00:00Z"
        )


        local_dt = dt.astimezone(
            TZ
        )


        model_values = {}


        for model_name in MODELS:

            model_values[
                model_name
            ] = (

                model_data
                .get(
                    model_name,
                    {}
                )
                .get(key)

            )


        valid_values = [

            value

            for value
            in model_values.values()

            if value is not None
        ]


        consensus = median(
            valid_values
        )


        if valid_values:

            spread_min = min(
                valid_values
            )

            spread_max = max(
                valid_values
            )

        else:

            spread_min = None

            spread_max = None


        forecast.append({

            "time":
                key,

            "localTime":
                local_dt.strftime(
                    "%-I:%M %p"
                ),

            "date":
                local_dt.strftime(
                    "%a, %b %-d"
                ),

            "models":
                model_values,

            "consensus":
                consensus,

            "spreadMin":
                clean_temp(
                    spread_min
                ),

            "spreadMax":
                clean_temp(
                    spread_max
                ),

            "modelCount":
                len(valid_values),
        })


    # --------------------------------------------------------
    # Current model values
    # --------------------------------------------------------

    current_key = current_hour.strftime(
        "%Y-%m-%dT%H:00:00Z"
    )


    current_models = {}


    for model_name in MODELS:

        current_models[
            model_name
        ] = (

            model_data
            .get(
                model_name,
                {}
            )
            .get(
                current_key
            )

        )


    current_values = [

        value

        for value
        in current_models.values()

        if value is not None
    ]


    current_consensus = median(
        current_values
    )


    if current_values:

        current_min = min(
            current_values
        )

        current_max = max(
            current_values
        )

    else:

        current_min = None

        current_max = None


    # --------------------------------------------------------
    # Daily peak calculations
    # --------------------------------------------------------

    daily_peaks = build_daily_peaks(
        forecast
    )


    # --------------------------------------------------------
    # Return everything
    # --------------------------------------------------------

    return {

        "location":
            "Central Park, New York",

        "station":
            NWS_STATION,

        "updatedAt":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "actual":
            actual,

        "past6Hours":
            history,

        "models":
            list(MODELS.keys()),

        "current": {

            "consensus":
                current_consensus,

            "minimum":
                clean_temp(
                    current_min
                ),

            "maximum":
                clean_temp(
                    current_max
                ),

            "modelCount":
                len(current_values),

            "models":
                current_models,
        },

        "forecast":
            forecast,

        "dailyPeaks":
            daily_peaks,
    }


# ============================================================
# HTML
# ============================================================

HTML = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
>

<title>
Central Park Weather
</title>


<style>

* {
    box-sizing: border-box;
}


body {

    margin: 0;

    background: #0b0b0b;

    color: #f5f5f5;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}


.container {

    width: 100%;

    max-width: 900px;

    margin: auto;

    padding: 18px;
}


h1 {

    margin: 0;

    font-size: 25px;
}


.subtitle {

    color: #999;

    margin-top: 5px;

    margin-bottom: 18px;
}


/* ==========================================================
   TABS
   ========================================================== */

.tabs {

    display: flex;

    gap: 8px;

    margin-bottom: 15px;
}


.tab {

    flex: 1;

    border: 1px solid #292929;

    background: #151515;

    color: #888;

    border-radius: 12px;

    padding: 13px;

    font-size: 14px;

    font-weight: 600;
}


.tab.active {

    background: #303030;

    color: white;
}


.tab-content {

    display: none;
}


.tab-content.active {

    display: block;
}


/* ==========================================================
   CARDS
   ========================================================== */

.card {

    background: #151515;

    border: 1px solid #282828;

    border-radius: 16px;

    padding: 18px;

    margin-bottom: 14px;
}


.section-title {

    font-size: 18px;

    font-weight: 650;

    margin-bottom: 13px;
}


.label {

    color: #999;

    font-size: 12px;

    letter-spacing: 1.5px;

    text-transform: uppercase;
}


.big {

    font-size: 58px;

    font-weight: 700;

    margin-top: 5px;
}


.actual {

    font-size: 18px;

    margin-top: 5px;
}


.actual span {

    color: #6fcf97;
}


.updated {

    color: #777;

    font-size: 12px;

    margin-top: 10px;
}


.spread {

    color: #aaa;

    font-size: 13px;

    margin-top: 8px;
}


/* ==========================================================
   MODEL CARDS
   ========================================================== */

.grid {

    display: grid;

    grid-template-columns:
        repeat(2, minmax(0, 1fr));

    gap: 10px;
}


.model {

    background: #101010;

    border: 1px solid #272727;

    border-radius: 12px;

    padding: 13px;
}


.model-name {

    color: #aaa;

    font-size: 13px;
}


.model-temp {

    font-size: 25px;

    font-weight: 650;

    margin-top: 5px;
}


.actual-box {

    border-color: #315b45;
}


/* ==========================================================
   HISTORY
   ========================================================== */

.history {

    display: grid;

    grid-template-columns:
        1fr 1fr;

    gap: 10px;
}


.history-box {

    background: #101010;

    padding: 14px;

    border-radius: 12px;
}


.history-value {

    font-size: 28px;

    font-weight: 650;
}


.history-label {

    color: #888;

    font-size: 12px;
}


/* ==========================================================
   HOURLY FORECAST
   ========================================================== */

.forecast-row {

    border-top: 1px solid #242424;

    padding: 13px 0;
}


.forecast-row:first-child {

    border-top: 0;
}


.forecast-top {

    display: flex;

    justify-content: space-between;

    align-items: center;
}


.forecast-time {

    font-weight: 600;
}


.forecast-date {

    color: #777;

    font-size: 11px;

    margin-top: 2px;
}


.consensus {

    font-size: 23px;

    font-weight: 700;
}


.model-values {

    display: grid;

    grid-template-columns:
        repeat(3, minmax(0, 1fr));

    gap: 5px;

    margin-top: 8px;
}


.small-model {

    color: #777;

    font-size: 10px;
}


.small-model strong {

    color: #bbb;

    font-size: 12px;
}


.count {

    color: #777;

    font-size: 11px;

    margin-top: 7px;
}


/* ==========================================================
   DAILY PEAK
   ========================================================== */

.peak-card {

    background: #151515;

    border: 1px solid #282828;

    border-radius: 16px;

    padding: 18px;

    margin-bottom: 14px;
}


.peak-date {

    font-size: 19px;

    font-weight: 650;
}


.peak-consensus {

    font-size: 48px;

    font-weight: 750;

    margin-top: 8px;
}


.peak-time {

    color: #999;

    margin-top: 2px;
}


.peak-models {

    display: grid;

    grid-template-columns:
        repeat(2, minmax(0, 1fr));

    gap: 8px;

    margin-top: 16px;
}


.peak-model {

    background: #101010;

    border-radius: 10px;

    padding: 10px;
}


.peak-model-name {

    color: #888;

    font-size: 11px;
}


.peak-model-temp {

    font-size: 20px;

    font-weight: 650;

    margin-top: 3px;
}


.peak-model-time {

    color: #666;

    font-size: 10px;

    margin-top: 2px;
}


/* ==========================================================
   NOTES
   ========================================================== */

.note {

    color: #777;

    font-size: 12px;

    line-height: 1.55;
}


/* ==========================================================
   BUTTON
   ========================================================== */

.refresh {

    width: 100%;

    padding: 14px;

    border: 0;

    border-radius: 12px;

    background: #252525;

    color: white;

    font-size: 15px;

    font-weight: 600;
}


.refresh:active {

    background: #333;
}


/* ==========================================================
   DESKTOP
   ========================================================== */

@media (min-width: 700px) {

    .grid {

        grid-template-columns:
            repeat(3, minmax(0, 1fr));
    }


    .model-values {

        grid-template-columns:
            repeat(6, minmax(0, 1fr));
    }


    .peak-models {

        grid-template-columns:
            repeat(3, minmax(0, 1fr));
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
        KNYC • Multi-Model Temperature Consensus
    </div>


    <!-- ====================================================
         TABS
         ==================================================== -->

    <div class="tabs">

        <button
            class="tab active"
            onclick="showTab('currentTab', this)"
        >
            Current
        </button>


        <button
            class="tab"
            onclick="showTab('peakTab', this)"
        >
            Daily Peak
        </button>

    </div>


    <!-- ====================================================
         CURRENT TAB
         ==================================================== -->

    <div
        id="currentTab"
        class="tab-content active"
    >


        <!-- CURRENT CONSENSUS -->

        <div class="card">

            <div class="label">
                Current Model Consensus
            </div>


            <div
                class="big"
                id="consensus"
            >
                —
            </div>


            <div
                class="actual"
                id="actual"
            >
                KNYC actual: —
            </div>


            <div
                class="spread"
                id="spread"
            >
                Model spread: —
            </div>


            <div
                class="updated"
                id="updated"
            >
                Updating...
            </div>

        </div>


        <!-- CURRENT MODELS -->

        <div class="card">

            <div class="section-title">
                Current Model Temperatures
            </div>


            <div
                class="grid"
                id="models"
            >
            </div>

        </div>


        <!-- PAST 6 HOURS -->

        <div class="card">

            <div class="section-title">
                Actual KNYC — Past 6 Hours
            </div>


            <div class="history">


                <div class="history-box">

                    <div class="history-label">
                        HIGH
                    </div>


                    <div
                        class="history-value"
                        id="high"
                    >
                        —
                    </div>

                </div>


                <div class="history-box">

                    <div class="history-label">
                        LOW
                    </div>


                    <div
                        class="history-value"
                        id="low"
                    >
                        —
                    </div>

                </div>


            </div>

        </div>


        <!-- HOURLY FORECAST -->

        <div class="card">

            <div class="section-title">
                Next 24 Hours
            </div>


            <div id="forecast">
                Loading...
            </div>

        </div>


    </div>


    <!-- ====================================================
         DAILY PEAK TAB
         ==================================================== -->

    <div
        id="peakTab"
        class="tab-content"
    >


        <div class="card">

            <div class="section-title">
                Predicted Daily Peak Temperature
            </div>


            <div class="note">

                Each day's peak is calculated by finding
                the highest hourly temperature predicted
                by each model, then taking the median of
                the available model peaks.

            </div>

        </div>


        <div id="dailyPeaks">

            Loading daily peaks...

        </div>


    </div>


    <!-- ====================================================
         DATA NOTES
         ==================================================== -->

    <div class="card">

        <div class="section-title">
            Data Notes
        </div>


        <div class="note">

            <strong>
                Models:
            </strong>

            ECMWF IFS • ECMWF AIFS • NBM • NAM •
            HRRR • GFS

            <br><br>


            <strong>
                Consensus:
            </strong>

            The consensus temperature is the median
            of the available model temperatures for
            the same hourly timestamp.

            <br><br>


            <strong>
                KNYC:
            </strong>

            The actual temperature is the latest
            National Weather Service observation
            from Central Park station KNYC.

            <br><br>


            <strong>
                Daily Peak:
            </strong>

            Each model's highest forecast temperature
            for that local calendar day is calculated
            first. The displayed daily consensus is
            then the median of those model peaks.

            <br><br>


            AIFS has native 6-hourly output, so its
            hourly values may be interpolated by the
            Open-Meteo API.

            <br><br>


            NBM is itself a statistical model blend,
            so the six model forecasts should not be
            interpreted as six completely independent
            forecasts.

        </div>

    </div>


    <button
        class="refresh"
        onclick="loadWeather()"
    >
        Refresh Weather
    </button>


</div>


<script>


// ============================================================
// TAB SWITCHING
// ============================================================

function showTab(
    tabId,
    button
) {

    document
        .querySelectorAll(
            ".tab-content"
        )
        .forEach(
            function(tab) {

                tab.classList.remove(
                    "active"
                );

            }
        );


    document
        .querySelectorAll(
            ".tab"
        )
        .forEach(
            function(tab) {

                tab.classList.remove(
                    "active"
                );

            }
        );


    document
        .getElementById(
            tabId
        )
        .classList.add(
            "active"
        );


    button.classList.add(
        "active"
    );
}


// ============================================================
// TEMPERATURE FORMAT
// ============================================================

function temp(value) {

    if (
        value === null ||
        value === undefined
    ) {

        return "—";

    }


    return (
        Number(value).toFixed(1)
        + "°F"
    );
}


// ============================================================
// SHORT MODEL NAMES
// ============================================================

function modelShortName(name) {

    const names = {

        "ECMWF IFS":
            "IFS",

        "ECMWF AIFS":
            "AIFS",

        "NBM":
            "NBM",

        "NAM":
            "NAM",

        "HRRR":
            "HRRR",

        "GFS":
            "GFS"
    };


    return names[name] || name;
}


// ============================================================
// LOAD WEATHER
// ============================================================

async function loadWeather() {

    try {


        const response =
            await fetch(
                "/api/weather?t="
                +
                Date.now()
            );


        if (!response.ok) {

            throw new Error(
                "HTTP "
                +
                response.status
            );

        }


        const data =
            await response.json();


        // ==================================================
        // CURRENT CONSENSUS
        // ==================================================

        document.getElementById(
            "consensus"
        ).textContent =
            temp(
                data.current.consensus
            );


        document.getElementById(
            "actual"
        ).innerHTML =
            "KNYC actual: "
            +
            "<span>"
            +
            temp(
                data.actual.temperature
            )
            +
            "</span>";


        if (
            data.current.minimum !== null
            &&
            data.current.maximum !== null
        ) {

            document.getElementById(
                "spread"
            ).textContent =
                "Model spread: "
                +
                temp(
                    data.current.minimum
                )
                +
                " – "
                +
                temp(
                    data.current.maximum
                );

        } else {

            document.getElementById(
                "spread"
            ).textContent =
                "Model spread: —";

        }


        const updated =
            new Date(
                data.updatedAt
            );


        document.getElementById(
            "updated"
        ).textContent =
            "Updated "
            +
            updated.toLocaleTimeString(
                [],
                {
                    hour: "numeric",
                    minute: "2-digit"
                }
            );


        // ==================================================
        // CURRENT MODELS
        // ==================================================

        const modelsContainer =
            document.getElementById(
                "models"
            );


        modelsContainer.innerHTML =
            "";


        // Actual KNYC card

        const actualCard =
            document.createElement(
                "div"
            );


        actualCard.className =
            "model actual-box";


        actualCard.innerHTML =

            '<div class="model-name">' +
                'KNYC ACTUAL' +
            '</div>' +

            '<div class="model-temp">' +
                temp(
                    data.actual.temperature
                ) +
            '</div>';


        modelsContainer.appendChild(
            actualCard
        );


        // Six model cards

        for (
            const name
            of data.models
        ) {


            const card =
                document.createElement(
                    "div"
                );


            card.className =
                "model";


            card.innerHTML =

                '<div class="model-name">' +
                    name +
                '</div>' +

                '<div class="model-temp">' +
                    temp(
                        data.current.models[
                            name
                        ]
                    ) +
                '</div>';


            modelsContainer.appendChild(
                card
            );

        }


        // ==================================================
        // PAST 6 HOURS
        // ==================================================

        document.getElementById(
            "high"
        ).textContent =
            temp(
                data.past6Hours.high
            );


        document.getElementById(
            "low"
        ).textContent =
            temp(
                data.past6Hours.low
            );


        // ==================================================
        // NEXT 24 HOURS
        // ==================================================

        const forecastContainer =
            document.getElementById(
                "forecast"
            );


        forecastContainer.innerHTML =
            "";


        data.forecast
            .slice(0, 24)
            .forEach(
                function(hour) {


                    const row =
                        document.createElement(
                            "div"
                        );


                    row.className =
                        "forecast-row";


                    let modelHTML =
                        "";


                    for (
                        const name
                        of data.models
                    ) {


                        modelHTML +=

                            '<div class="small-model">' +

                                modelShortName(
                                    name
                                )

                                +

                                '<br><strong>' +

                                temp(
                                    hour.models[
                                        name
                                    ]
                                )

                                +

                                '</strong>' +

                            '</div>';

                    }


                    row.innerHTML =

                        '<div class="forecast-top">' +

                            '<div>' +

                                '<div class="forecast-time">' +
                                    hour.localTime +
                                '</div>' +

                                '<div class="forecast-date">' +
                                    hour.date +
                                '</div>' +

                            '</div>' +


                            '<div class="consensus">' +

                                temp(
                                    hour.consensus
                                )

                            + '</div>' +

                        '</div>' +


                        '<div class="model-values">' +

                            modelHTML +

                        '</div>' +


                        '<div class="count">' +

                            hour.modelCount +

                            '/6 models available' +

                        '</div>';


                    forecastContainer.appendChild(
                        row
                    );

                }
            );


        // ==================================================
        // DAILY PEAKS
        // ==================================================

        const peaksContainer =
            document.getElementById(
                "dailyPeaks"
            );


        peaksContainer.innerHTML =
            "";


        data.dailyPeaks
            .slice(0, 3)
            .forEach(
                function(day, index) {


                    const card =
                        document.createElement(
                            "div"
                        );


                    card.className =
                        "peak-card";


                    let title =
                        day.displayDate;


                    if (
                        index === 0
                    ) {

                        title +=
                            " • Today";

                    }


                    if (
                        index === 1
                    ) {

                        title +=
                            " • Tomorrow";

                    }


                    if (
                        index === 2
                    ) {

                        title +=
                            " • Day After";

                    }


                    let modelHTML =
                        "";


                    for (
                        const name
                        of data.models
                    ) {


                        const model =
                            day.models[
                                name
                            ];


                        modelHTML +=

                            '<div class="peak-model">' +

                                '<div class="peak-model-name">' +

                                    name +

                                '</div>' +


                                '<div class="peak-model-temp">' +

                                    temp(
                                        model.temperature
                                    ) +

                                '</div>' +


                                '<div class="peak-model-time">' +

                                    (
                                        model.time
                                        ||
                                        "—"
                                    ) +

                                '</div>' +

                            '</div>';

                    }


                    card.innerHTML =

                        '<div class="peak-date">' +

                            title +

                        '</div>' +


                        '<div class="peak-consensus">' +

                            temp(
                                day.consensus
                            ) +

                        '</div>' +


                        '<div class="peak-time">' +

                            'Predicted peak around ' +

                            (
                                day.consensusTime
                                ||
                                "—"
                            ) +

                        '</div>' +


                        '<div class="peak-models">' +

                            modelHTML +

                        '</div>' +


                        '<div class="count">' +

                            day.modelCount +

                            '/6 models available' +

                        '</div>';


                    peaksContainer.appendChild(
                        card
                    );

                }
            );


    } catch (error) {


        console.error(
            "Weather update error:",
            error
        );


        document.getElementById(
            "updated"
        ).textContent =
            "Weather update failed.";


        document.getElementById(
            "consensus"
        ).textContent =
            "—";

    }

}


// ============================================================
// INITIAL LOAD
// ============================================================

loadWeather();


// ============================================================
// AUTO REFRESH EVERY 5 MINUTES
// ============================================================

setInterval(
    loadWeather,
    5 * 60 * 1000
);


</script>


</body>

</html>
"""


# ============================================================
# HTTP SERVER
# ============================================================

class WeatherHandler(
    BaseHTTPRequestHandler
):


    def send_text(
        self,
        content,
        content_type="text/html; charset=utf-8",
        status=200
    ):


        encoded =
            content.encode(
                "utf-8"
            )


        self.send_response(
            status
        )


        self.send_header(
            "Content-Type",
            content_type
        )


        self.send_header(
            "Content-Length",
            str(
                len(encoded)
            )
        )


        self.send_header(
            "Cache-Control",
            "no-store"
        )


        self.end_headers()


        self.wfile.write(
            encoded
        )


    def do_GET(self):


        path = (
            self.path
            .split("?")[0]
        )


        # ----------------------------------------------------
        # API
        # ----------------------------------------------------

        if path == "/api/weather":


            try:


                weather =
                    get_weather()


                payload =
                    json.dumps(
                        weather,
                        separators=(
                            ",",
                            ":"
                        )
                    )


                self.send_text(

                    payload,

                    "application/json; charset=utf-8",

                    200

                )


            except Exception as error:


                print(
                    "API ERROR:",
                    error
                )


                payload =
                    json.dumps({

                        "error":
                            str(error)

                    })


                self.send_text(

                    payload,

                    "application/json; charset=utf-8",

                    500

                )


            return


        # ----------------------------------------------------
        # WEBSITE
        # ----------------------------------------------------

        self.send_text(

            HTML,

            "text/html; charset=utf-8",

            200

        )


    def log_message(
        self,
        format,
        *args
    ):


        print(
            "%s - %s"
            %
            (
                self.address_string(),
                format % args
            )
        )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":


    print(
        "========================================"
    )

    print(
        "Central Park Weather Server"
    )

    print(
        "KNYC Multi-Model Consensus"
    )

    print(
        "========================================"
    )

    print(
        "Listening on "
        + HOST
        + ":"
        + str(PORT)
    )


    server =
        ThreadingHTTPServer(
            (
                HOST,
                PORT
            ),
            WeatherHandler
        )


    try:

        server.serve_forever()


    except KeyboardInterrupt:

        print(
            "Server stopped."
        )


    finally:

        server.server_close()
