from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlparse
import json, time

LAT,LON=40.78,-73.97
UA="CentralParkWeatherPredictor/1.0 (local personal weather dashboard)"
CACHE={"time":0,"data":None}

def get_json(url):
    req=Request(url,headers={"User-Agent":UA,"Accept":"application/geo+json"})
    with urlopen(req,timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def build():
    # Refresh the points mapping each time; NWS recommends periodically checking it.
    point=get_json(f"https://api.weather.gov/points/{LAT},{LON}")
    forecast_url=point["properties"]["forecastHourly"]
    stations_url=point["properties"]["observationStations"]
    forecast=get_json(forecast_url)
    stations=get_json(stations_url)
    station=next((x for x in stations["features"]
                  if x["properties"].get("stationIdentifier")=="KNYC"),
                 stations["features"][0])
    station_id=station["properties"].get("stationIdentifier","KNYC")
    obs=get_json(f"{station['id']}/observations/latest")["properties"]
    temp_c=obs.get("temperature",{}).get("value")
    wind_kmh=obs.get("windSpeed",{}).get("value")
    humidity=obs.get("relativeHumidity",{}).get("value")
    current={
        "temperatureF": None if temp_c is None else temp_c*9/5+32,
        "humidity": humidity,
        "windMph": None if wind_kmh is None else wind_kmh*0.621371,
        "textDescription": obs.get("textDescription")
    }
    periods=[]
    for p in forecast["properties"]["periods"][:24]:
        periods.append({
            "startTime":p["startTime"],
            "temperature":p.get("temperature"),
            "temperatureUnit":p.get("temperatureUnit"),
            "shortForecast":p.get("shortForecast"),
            "pop":(p.get("probabilityOfPrecipitation") or {}).get("value")
        })
    return {"station":station_id,"current":current,"forecast":periods,"fetchedAt":time.time()*1000}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path.startswith("/api/weather"):
                now=time.time()
                # Cache for 60 seconds to avoid hammering NWS while still feeling live.
                if CACHE["data"] is None or now-CACHE["time"]>60:
                    CACHE["data"]=build()
                    CACHE["time"]=now
                body=json.dumps(CACHE["data"]).encode()
                self.send_response(200)
                self.send_header("Content-Type","application/json; charset=utf-8")
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            path="/index.html" if self.path=="/" else self.path.split("?")[0]
            if path!="/index.html":
                self.send_error(404); return
            body=open("index.html","rb").read()
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers(); self.wfile.write(body)
        except Exception as e:
            body=json.dumps({"error":str(e)}).encode()
            self.send_response(502)
            self.send_header("Content-Type","application/json")
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers(); self.wfile.write(body)
    def log_message(self,*args): pass

print("Central Park Weather Predictor running at http://")
ThreadingHTTPServer(("127.0.0.1",8000),Handler).serve_forever()
