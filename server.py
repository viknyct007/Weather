from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
import json
import os
import time

LAT, LON = 40.78, -73.97
UA = "CentralParkWeather/1.0"

def get_json(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read())

def weather():
    point = get_json(f"https://api.weather.gov/points/{LAT},{LON}")

    forecast = get_json(point["properties"]["forecastHourly"])
    stations = get_json(point["properties"]["observationStations"])

    station = next(
        s for s in stations["features"]
        if s["properties"].get("stationIdentifier") == "KNYC"
    )

    obs = get_json(
        station["id"] + "/observations/latest"
    )["properties"]

    temp = obs.get("temperature", {}).get("value")
    wind = obs.get("windSpeed", {}).get("value")
    description = obs.get("textDescription")

    return {
        "station": "KNYC",
        "fetchedAt": time.time() * 1000,

        "current": {
            "temperatureF": None if temp is None else temp * 9 / 5 + 32,
            "humidity": obs.get("relativeHumidity", {}).get("value"),
            "windMph": None if wind is None else wind * 0.621371,
            "description": description,
            "textDescription": description
        },

        "forecast": [
            {
                "time": p["startTime"],
                "startTime": p["startTime"],
                "temperature": p["temperature"],
                "temperatureUnit": p["temperatureUnit"],
                "unit": p["temperatureUnit"],
                "shortForecast": p["shortForecast"],
                "forecast": p["shortForecast"],
                "pop": (
                    p.get("probabilityOfPrecipitation") or {}
                ).get("value"),
                "precipitation": (
                    p.get("probabilityOfPrecipitation") or {}
                ).get("value")
            }
            for p in forecast["properties"]["periods"][:24]
        ]
    }

class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            if self.path.startswith("/api/weather"):
                data = json.dumps(weather()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")

            else:
                with open("index.html", "rb") as f:
                    data = f.read()

                self.send_response(200)
                self.send_header("Content-Type", "text/html")

            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        except Exception as e:
            data = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    def log_message(self, *args):
        pass

port = int(os.environ.get("PORT", 10000))

print(f"Server running on port {port}")

server = ThreadingHTTPServer(
    ("0.0.0.0", port),
    Handler
)

server.serve_forever()
