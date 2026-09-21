<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Central Park Weather</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Roboto, Arial, sans-serif;
    background: #f2f4f7;
    color: #111;
}

.container {
    max-width: 700px;
    margin: auto;
    padding: 16px;
}

h1 {
    margin: 5px 0 4px;
    font-size: 28px;
}

.subtitle {
    color: #666;
    margin-bottom: 18px;
}

.card {
    background: white;
    border-radius: 18px;
    padding: 18px;
    margin-bottom: 15px;
    box-shadow: 0 2px 10px rgba(0,0,0,.06);
}

.current {
    text-align: center;
}

.current-temp {
    font-size: 58px;
    font-weight: 700;
    margin: 8px 0;
}

.description {
    font-size: 18px;
    color: #555;
}

.updated {
    font-size: 12px;
    color: #888;
    margin-top: 8px;
}

h2 {
    margin-top: 0;
    font-size: 20px;
}

.stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
}

.stat {
    background: #f5f6f8;
    border-radius: 14px;
    padding: 14px;
}

.label {
    color: #666;
    font-size: 13px;
    margin-bottom: 5px;
}

.value {
    font-size: 25px;
    font-weight: 700;
}

.small {
    color: #777;
    font-size: 13px;
    margin-top: 4px;
}

.hour {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 13px 4px;
    border-bottom: 1px solid #eee;
}

.hour:last-child {
    border-bottom: none;
}

.hour-time {
    width: 25%;
    font-weight: 600;
}

.hour-temp {
    width: 25%;
    font-size: 19px;
    font-weight: 700;
}

.hour-weather {
    width: 35%;
    color: #555;
    font-size: 14px;
}

.hour-rain {
    width: 15%;
    text-align: right;
    color: #2878c8;
    font-size: 13px;
}

.source-box {
    font-size: 13px;
    color: #666;
    line-height: 1.6;
}

.source {
    display: inline-block;
    background: #f0f1f3;
    padding: 4px 8px;
    border-radius: 8px;
    margin: 3px;
}

.error {
    background: #fff0f0;
    color: #b00020;
    padding: 12px;
    border-radius: 12px;
    display: none;
    margin-bottom: 15px;
}

.loading {
    text-align: center;
    padding: 20px;
    color: #777;
}

.refresh {
    display: block;
    width: 100%;
    border: none;
    border-radius: 12px;
    padding: 13px;
    background: #111;
    color: white;
    font-size: 15px;
    cursor: pointer;
    margin-top: 10px;
}

.refresh:active {
    opacity: .7;
}

@media (max-width: 500px) {

    .container {
        padding: 12px;
    }

    h1 {
        font-size: 25px;
    }

    .current-temp {
        font-size: 52px;
    }

    .hour-weather {
        font-size: 12px;
    }
}
</style>
</head>

<body>

<div class="container">

    <h1>Central Park Weather</h1>

    <div class="subtitle">
        KNYC • New York City
    </div>

    <div id="error" class="error"></div>

    <!-- CURRENT CONDITIONS -->

    <div class="card current">

        <div class="label">
            CURRENT TEMPERATURE
        </div>

        <div id="currentTemp"
             class="current-temp">
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


    <!-- CURRENT DETAILS -->

    <div class="card">

        <h2>Current Conditions</h2>

        <div class="stats">

            <div class="stat">

                <div class="label">
                    Humidity
                </div>

                <div id="humidity"
                     class="value">
                    --%
                </div>

            </div>

            <div class="stat">

                <div class="label">
                    Wind
                </div>

                <div id="wind"
                     class="value">
                    --.- mph
                </div>

            </div>

        </div>

    </div>


    <!-- PAST 6 HOURS -->

    <div class="card">

        <h2>Past 6 Hours</h2>

        <div class="stats">

            <div class="stat">

                <div class="label">
                    PEAK TEMPERATURE
                </div>

                <div id="sixHourHigh"
                     class="value">
                    --.-°F
                </div>

                <div id="sixHourHighTime"
                     class="small">
                    --
                </div>

            </div>


            <div class="stat">

                <div class="label">
                    LOWEST TEMPERATURE
                </div>

                <div id="sixHourLow"
                     class="value">
                    --.-°F
                </div>

                <div id="sixHourLowTime"
                     class="small">
                    --
                </div>

            </div>

        </div>

    </div>


    <!-- FORECAST SOURCES -->

    <div class="card">

        <h2>Forecast Sources</h2>

        <div id="sources"
             class="source-box">
            Loading...
        </div>

    </div>


    <!-- HOURLY FORECAST -->

    <div class="card">

        <h2>Next 24 Hours</h2>

        <div id="forecast">

            <div class="loading">
                Loading forecast...
            </div>

        </div>

    </div>


    <button class="refresh"
            onclick="loadWeather()">

        Refresh Weather

    </button>

</div>


<script>

async function loadWeather() {

    const errorBox =
        document.getElementById("error");

    errorBox.style.display = "none";

    try {

        const response =
            await fetch(
                "/api/weather?time=" +
                Date.now(),
                {
                    cache: "no-store"
                }
            );

        if (!response.ok) {
            throw new Error(
                "Weather server returned " +
                response.status
            );
        }

        const data =
            await response.json();

        displayWeather(data);

    } catch (error) {

        console.error(error);

        errorBox.textContent =
            "Unable to load weather: " +
            error.message;

        errorBox.style.display =
            "block";
    }
}


function displayWeather(data) {

    /*
     * CURRENT CONDITIONS
     */

    const current =
        data.current || {};

    if (current.temperatureF != null) {

        document.getElementById(
            "currentTemp"
        ).textContent =
            Number(
                current.temperatureF
            ).toFixed(1) + "°F";
    }

    document.getElementById(
        "description"
    ).textContent =
        current.description ||
        "Conditions unavailable";


    if (current.humidity != null) {

        document.getElementById(
            "humidity"
        ).textContent =
            Number(
                current.humidity
            ).toFixed(0) + "%";
    }


    if (current.windMph != null) {

        document.getElementById(
            "wind"
        ).textContent =
            Number(
                current.windMph
            ).toFixed(1) +
            " mph";
    }


    /*
     * UPDATED TIME
     */

    if (data.fetchedAt) {

        document.getElementById(
            "updated"
        ).textContent =
            "Updated " +
            new Date(
                data.fetchedAt
            ).toLocaleTimeString(
                [],
                {
                    hour: "numeric",
                    minute: "2-digit"
                }
            );
    }


    /*
     * PAST 6-HOUR HIGH / LOW
     */

    const sixHour =
        data.sixHour || {};


    if (sixHour.high) {

        document.getElementById(
            "sixHourHigh"
        ).textContent =
            Number(
                sixHour.high.temperature
            ).toFixed(1) + "°F";


        document.getElementById(
            "sixHourHighTime"
        ).textContent =
            formatTime(
                sixHour.high.time
            );
    }


    if (sixHour.low) {

        document.getElementById(
            "sixHourLow"
        ).textContent =
            Number(
                sixHour.low.temperature
            ).toFixed(1) + "°F";


        document.getElementById(
            "sixHourLowTime"
        ).textContent =
            formatTime(
                sixHour.low.time
            );
    }


    /*
     * FORECAST SOURCES
     */

    const providers =
        data.providers || {};

    const sourceBox =
        document.getElementById(
            "sources"
        );

    sourceBox.innerHTML = "";


    Object.entries(
        providers
    ).forEach(
        ([name, available]) => {

            if (available) {

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

        }
    );


    /*
     * HOURLY FORECAST
     */

    const forecast =
        data.forecast || [];

    const forecastBox =
        document.getElementById(
            "forecast"
        );

    forecastBox.innerHTML = "";


    forecast.slice(
        0,
        24
    ).forEach(
        period => {

            const row =
                document.createElement(
                    "div"
                );

            row.className =
                "hour";


            const time =
                formatTime(
                    period.time
                );


            const temp =
                period.temperature != null
                ? Number(
                    period.temperature
                  ).toFixed(1) + "°F"
                : "--.-°F";


            const weather =
                period.shortForecast ||
                "—";


            const rain =
                period.pop != null
                ? Number(
                    period.pop
                  ).toFixed(0) + "%"
                : "—";


            row.innerHTML = `

                <div class="hour-time">
                    ${time}
                </div>

                <div class="hour-temp">
                    ${temp}
                </div>

                <div class="hour-weather">
                    ${weather}
                </div>

                <div class="hour-rain">
                    ${rain}
                </div>

            `;


            forecastBox.appendChild(
                row
            );

        }
    );

}


function formatTime(timestamp) {

    if (!timestamp) {
        return "--";
    }

    const date =
        new Date(timestamp);

    if (isNaN(date.getTime())) {
        return "--";
    }

    return date.toLocaleTimeString(
        [],
        {
            hour: "numeric",
            minute: "2-digit"
        }
    );
}


/*
 * LOAD IMMEDIATELY
 */

loadWeather();


/*
 * AUTO REFRESH EVERY 5 MINUTES
 */

setInterval(
    loadWeather,
    5 * 60 * 1000
);

</script>

</body>
</html>
