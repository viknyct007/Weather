from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import statistics
import time


# ============================================================
# CENTRAL PARK / KNYC WEATHER MODEL CONSENSUS
# ============================================================

LAT = 40.7812
LON = -73.9665

TZ = ZoneInfo("America/New_York")

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "10000"))

USER_AGENT = "CentralParkWeatherApp/6.0"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

NWS_STATION = "KNYC"


# ============================================================
# MODEL CONFIGURATION
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
# HTTP HELPERS
# ============================================================

def get_json(url, timeout=20):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
        return json.loads(data)


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
        float(v)
        for v in values
        if v is not None
    ]

    if not values:
        return None

    return round(statistics.median(values), 1)


def iso_to_datetime(value):
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except Exception:
        return None


# ============================================================
# KNYC ACTUAL OBSERVATION
# ============================================================

def get_knyc_observation():

    url = (
        "https://api.weather.gov/stations/"
        + NWS_STATION
        + "/observations/latest"
    )

    try:
        data = get_json(url)

        props = data.get("properties", {})

        temperature = props.get("temperature", {}).get("value")

        if temperature is not None:
            temperature_f = (temperature * 9 / 5) + 32
        else:
            temperature_f = None

        humidity = props.get("relativeHumidity", {}).get("value")

        wind_speed = props.get("windSpeed", {}).get("value")

        if wind_speed is not None:
            wind_mph = wind_speed * 0.621371
        else:
            wind_mph = None

        timestamp = props.get("timestamp")

        return {
            "temperature": clean_temp(temperature_f),
            "humidity": round(humidity, 1)
            if humidity is not None
            else None,
            "wind_mph": round(wind_mph, 1)
            if wind_mph is not None
            else None,
            "description": props.get("textDescription"),
            "timestamp": timestamp,
            "station": NWS_STATION,
        }

    except Exception as error:

        print("KNYC observation error:", error)

        return {
            "temperature": None,
            "humidity": None,
            "wind_mph": None,
            "description": None,
            "timestamp": None,
            "station": NWS_STATION,
        }


# ============================================================
# KNYC PAST 6 HOURS
# ============================================================

def get_knyc_history():

    now = datetime.now(timezone.utc)

    start = now - timedelta(hours=6)

    start_text = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_text = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    params = urlencode({
        "start": start_text,
        "end": end_text,
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

        for item in data.get("features", []):

            props = item.get("properties", {})

            value = props.get(
                "temperature",
                {}
            ).get("value")

            if value is None:
                continue

            temp_f = (value * 9 / 5) + 32

            temperatures.append(
                round(temp_f, 1)
            )

        if not temperatures:

            return {
                "high": None,
                "low": None,
            }

        return {
            "high": max(temperatures),
            "low": min(temperatures),
        }

    except Exception as error:

        print("KNYC history error:", error)

        return {
            "high": None,
            "low": None,
        }


# ============================================================
# MODEL FORECAST
# ============================================================

def get_model_forecast(model_id):

    params = {
        "latitude": str(LAT),
        "longitude": str(LON),
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "UTC",
        "forecast_days": "3",
        "models": model_id,
    }

    url = OPEN_METEO_URL + "?" + urlencode(params)

    try:

        data = get_json(url)

        hourly = data.get("hourly", {})

        times = hourly.get("time", [])
        temperatures = hourly.get(
            "temperature_2m",
            []
        )

        result = {}

        for timestamp, temperature in zip(
            times,
            temperatures
        ):

            dt = iso_to_datetime(timestamp)

            if dt is None:
                continue

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            dt = dt.astimezone(timezone.utc)

            key = dt.strftime(
                "%Y-%m-%dT%H:00:00Z"
            )

            result[key] = clean_temp(
                temperature
            )

        return result

    except Exception as error:

        print(
            "Model error",
            model_id,
            ":",
            error
        )

        return {}


# ============================================================
# WEATHER DATA
# ============================================================

def get_weather():

    now = datetime.now(timezone.utc)

    current_hour = now.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    # --------------------------------------------------------
    # Actual KNYC observation
    # --------------------------------------------------------

    observation = get_knyc_observation()

    history = get_knyc_history()

    # --------------------------------------------------------
    # Fetch all six models
    # --------------------------------------------------------

    model_data = {}

    for model_name, model_id in MODELS.items():

        print(
            "Fetching",
            model_name,
            model_id
        )

        model_data[model_name] = get_model_forecast(
            model_id
        )

    # --------------------------------------------------------
    # Build 48 aligned hourly timestamps
    # --------------------------------------------------------

    hours = []

    for i in range(48):

        dt = current_hour + timedelta(
            hours=i
        )

        key = dt.strftime(
            "%Y-%m-%dT%H:00:00Z"
        )

        hours.append({
            "key": key,
            "datetime": dt,
        })

    # --------------------------------------------------------
    # Construct hourly model consensus
    # --------------------------------------------------------

    forecast = []

    for hour in hours:

        key = hour["key"]

        values = {}

        for model_name in MODELS:

            temperature = model_data.get(
                model_name,
                {}
            ).get(key)

            values[model_name] = temperature

        valid_values = [
            value
            for value in values.values()
            if value is not None
        ]

        consensus = median(valid_values)

        if valid_values:

            spread_min = min(valid_values)
            spread_max = max(valid_values)

        else:

            spread_min = None
            spread_max = None

        forecast.append({
            "time": key,
            "localTime": hour["datetime"]
                .astimezone(TZ)
                .strftime("%-I:%M %p"),
            "date": hour["datetime"]
                .astimezone(TZ)
                .strftime("%a, %b %-d"),
            "models": values,
            "consensus": consensus,
            "spreadMin": clean_temp(
                spread_min
            ),
            "spreadMax": clean_temp(
                spread_max
            ),
            "modelCount": len(valid_values),
        })

    # --------------------------------------------------------
    # Current model values
    # --------------------------------------------------------

    current_models = {}

    for model_name in MODELS:

        current_models[model_name] = (
            model_data
            .get(model_name, {})
            .get(
                current_hour.strftime(
                    "%Y-%m-%dT%H:00:00Z"
                )
            )
        )

    current_values = [
        value
        for value in current_models.values()
        if value is not None
    ]

    current_consensus = median(
        current_values
    )

    current_min = (
        min(current_values)
        if current_values
        else None
    )

    current_max = (
        max(current_values)
        if current_values
        else None
    )

    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return {
        "location": "Central Park, New York",
        "station": "KNYC",

        "updatedAt": datetime.now(
            timezone.utc
        ).isoformat(),

        "actual": observation,

        "past6Hours": history,

        "current": {
            "consensus": current_consensus,
            "minimum": clean_temp(
                current_min
            ),
            "maximum": clean_temp(
                current_max
            ),
            "modelCount": len(
                current_values
            ),
            "models": current_models,
        },

        "models": list(
            MODELS.keys()
        ),

        "forecast": forecast,
    }


# ============================================================
# WEBSITE
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
Central Park Weather Model Consensus
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
    font-size: 25px;
    margin: 0;
}

.subtitle {
    color: #999;
    margin-top: 5px;
    margin-bottom: 20px;
}

.card {
    background: #151515;
    border: 1px solid #282828;
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 14px;
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
    margin-top: 4px;
}

.actual span {
    color: #6fcf97;
}

.updated {
    color: #777;
    font-size: 12px;
    margin-top: 10px;
}

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
    font-size: 13px;
    color: #aaa;
}

.model-temp {
    font-size: 25px;
    font-weight: 650;
    margin-top: 5px;
}

.actual-box {
    border-color: #315b45;
}

.section-title {
    font-size: 18px;
    font-weight: 650;
    margin-bottom: 13px;
}

.spread {
    color: #aaa;
    font-size: 13px;
    margin-top: 8px;
}

.history {
    display: grid;
    grid-template-columns: 1fr 1fr;
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

.note {
    color: #777;
    font-size: 12px;
    line-height: 1.5;
}

button {
    width: 100%;
    padding: 14px;
    border: 0;
    border-radius: 12px;
    background: #252525;
    color: white;
    font-size: 15px;
}

button:active {
    background: #333;
}

@media (min-width: 700px) {

    .grid {
        grid-template-columns:
            repeat(3, minmax(0, 1fr));
    }

    .model-values {
        grid-template-columns:
            repeat(6, minmax(0, 1fr));
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


    <div class="card">

        <div class="section-title">
            Next 24 Hours
        </div>

        <div id="forecast">
            Loading...
        </div>

    </div>


    <div class="card">

        <div class="section-title">
            Data Notes
        </div>

        <div class="note">

            Consensus = median temperature from the
            available model forecasts for the same
            hourly timestamp.

            <br><br>

            Models:

            ECMWF IFS • ECMWF AIFS • NBM • NAM •
            HRRR • GFS

            <br><br>

            KNYC actual temperature comes separately
            from the National Weather Service station
            observation.

            <br><br>

            The model consensus is not a statistical
            guarantee. NBM is itself a multi-model
            statistical blend, so the six models are
            not six completely independent forecasts.

        </div>

    </div>


    <button onclick="loadWeather()">
        Refresh Weather
    </button>

</div>


<script>

function temp(value) {

    if (
        value === null ||
        value === undefined
    ) {
        return "—";
    }

    return Number(value).toFixed(1) + "°F";
}


function modelShortName(name) {

    const names = {
        "ECMWF IFS": "IFS",
        "ECMWF AIFS": "AIFS",
        "NBM": "NBM",
        "NAM": "NAM",
        "HRRR": "HRRR",
        "GFS": "GFS"
    };

    return names[name] || name;
}


async function loadWeather() {

    try {

        const response =
            await fetch(
                "/api/weather?t=" +
                Date.now()
            );

        const data =
            await response.json();


        // --------------------------------------------------
        // Current consensus
        // --------------------------------------------------

        document.getElementById(
            "consensus"
        ).textContent =
            temp(
                data.current.consensus
            );


        document.getElementById(
            "actual"
        ).innerHTML =
            "KNYC actual: <span>" +
            temp(
                data.actual.temperature
            ) +
            "</span>";


        if (
            data.current.minimum !== null &&
            data.current.maximum !== null
        ) {

            document.getElementById(
                "spread"
            ).textContent =
                "Model spread: " +
                temp(
                    data.current.minimum
                ) +
                " – " +
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
            "Updated " +
            updated.toLocaleTimeString(
                [],
                {
                    hour: "numeric",
                    minute: "2-digit"
                }
            );


        // --------------------------------------------------
        // Current models
        // --------------------------------------------------

        const models =
            document.getElementById(
                "models"
            );

        models.innerHTML = "";


        const actualBox =
            document.createElement(
                "div"
            );

        actualBox.className =
            "model actual-box";

        actualBox.innerHTML =
            '<div class="model-name">' +
            'KNYC ACTUAL' +
            '</div>' +
            '<div class="model-temp">' +
            temp(
                data.actual.temperature
            ) +
            '</div>';

        models.appendChild(
            actualBox
        );


        for (
            const name of data.models
        ) {

            const box =
                document.createElement(
                    "div"
                );

            box.className =
                "model";

            box.innerHTML =
                '<div class="model-name">' +
                name +
                '</div>' +
                '<div class="model-temp">' +
                temp(
                    data.current.models[name]
                ) +
                '</div>';

            models.appendChild(box);
        }


        // --------------------------------------------------
        // History
        // --------------------------------------------------

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


        // --------------------------------------------------
        // Forecast
        // --------------------------------------------------

        const forecast =
            document.getElementById(
                "forecast"
            );

        forecast.innerHTML = "";


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


                    let modelHTML = "";


                    for (
                        const name of data.models
                    ) {

                        modelHTML +=
                            '<div class="small-model">' +
                            modelShortName(name) +
                            '<br><strong>' +
                            temp(
                                hour.models[name]
                            ) +
                            '</strong></div>';

                    }


                    row.innerHTML =

                        '<div class="forecast-top">' +

                            '<div class="forecast-time">' +
                                hour.localTime +
                                '<br>' +
                                '<span style="color:#777;font-size:11px;">' +
                                hour.date +
                                '</span>' +
                            '</div>' +

                            '<div class="consensus">' +
                                temp(
                                    hour.consensus
                                ) +
                            '</div>' +

                        '</div>' +

                        '<div class="model-values">' +
                            modelHTML +
                        '</div>' +

                        '<div class="count">' +
                            hour.modelCount +
                            '/6 models available' +
                        '</div>';


                    forecast.appendChild(
                        row
                    );

                }
            );


    } catch (error) {

        console.error(error);

        document.getElementById(
            "updated"
        ).textContent =
            "Weather update failed.";

    }

}


// Initial load
loadWeather();


// Refresh every 5 minutes
setInterval(
    loadWeather,
    5 * 60 * 1000
);

</script>

</body>

</html>
"""


# ============================================================
# SERVER
# ============================================================

class WeatherHandler(BaseHTTPRequestHandler):

    def send_text(
        self,
        content,
        content_type="text/html; charset=utf-8",
        status=200,
    ):

        encoded = content.encode(
            "utf-8"
        )

        self.send_response(status)

        self.send_header(
            "Content-Type",
            content_type
        )

        self.send_header(
            "Content-Length",
            str(len(encoded))
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

        path = self.path.split("?")[0]

        # ----------------------------------------------------
        # API
        # ----------------------------------------------------

        if path == "/api/weather":

            try:

                weather = get_weather()

                payload = json.dumps(
                    weather,
                    separators=(",", ":")
                )

                self.send_text(
                    payload,
                    "application/json; charset=utf-8"
                )

            except Exception as error:

                print(
                    "API ERROR:",
                    error
                )

                payload = json.dumps({
                    "error": str(error)
                })

                self.send_text(
                    payload,
                    "application/json; charset=utf-8",
                    500
                )

            return


        # ----------------------------------------------------
        # Website
        # ----------------------------------------------------

        self.send_text(
            HTML,
            "text/html; charset=utf-8"
        )


    def log_message(
        self,
        format,
        *args
    ):

        print(
            "%s - %s"
            % (
                self.address_string(),
                format % args
            )
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    print(
        "Starting Central Park Weather Server..."
    )

    print(
        "Listening on "
        + HOST
        + ":"
        + str(PORT)
    )

    server = ThreadingHTTPServer(
        (HOST, PORT),
        WeatherHandler
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        pass

    finally:

        server.server_close()
