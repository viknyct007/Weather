from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
import os
import statistics

LAT = 40.7812
LON = -73.9665
TZ = ZoneInfo("America/New_York")
PORT = int(os.environ.get("PORT", "10000"))
UA = "CentralParkWeather/9.0"

# Open-Meteo model IDs. These are model outputs, not six independent weather APIs.
MODELS = {
    "ECMWF IFS": "ecmwf_ifs",
    "ECMWF AIFS": "ecmwf_aifs025_single",
    "NBM": "ncep_nbm_conus",
    "NAM": "ncep_nam_conus",
    "HRRR": "ncep_hrrr_conus",
    "GFS": "ncep_gfs_global",
}


def fetch_json(url, timeout=25):
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def temp_f(value_c):
    if value_c is None:
        return None
    try:
        return round(float(value_c) * 9.0 / 5.0 + 32.0, 1)
    except (TypeError, ValueError):
        return None


def clean_temp(value):
    if value is None:
        return None
    try:
        value = float(value)
        return round(value, 1) if value == value else None
    except (TypeError, ValueError):
        return None


def med(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else None


def parse_utc(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def fmt_time(dt):
    # Cross-platform replacement for strftime('%-I:%M %p').
    s = dt.strftime("%I:%M %p")
    return s[1:] if s.startswith("0") else s


def fmt_date(dt):
    return dt.strftime("%a, %b ") + str(dt.day)


def fmt_day(dt):
    return dt.strftime("%A, %B ") + str(dt.day)


def get_knyc_actual():
    url = "https://api.weather.gov/stations/KNYC/observations/latest"
    try:
        p = fetch_json(url).get("properties", {})
        temp = p.get("temperature", {}).get("value")
        rh = p.get("relativeHumidity", {}).get("value")
        wind = p.get("windSpeed", {}).get("value")
        return {
            "temperature": temp_f(temp),
            "humidity": round(float(rh), 1) if rh is not None else None,
            "windMph": round(float(wind) * 2.236936, 1) if wind is not None else None,
            "description": p.get("textDescription"),
            "timestamp": p.get("timestamp"),
            "station": "KNYC",
        }
    except Exception as e:
        print("KNYC error:", e)
        return {"temperature": None, "humidity": None, "windMph": None, "description": None, "timestamp": None, "station": "KNYC"}


def get_knyc_peak_today():
    # Find the highest temperature NWS has observed at KNYC today.
    # We query from local midnight through now, then filter by the
    # observation's local calendar date. This is more useful here than
    # a rolling six-hour high/low.
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(TZ)
    local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = local_midnight.astimezone(timezone.utc)

    params = urlencode({
        "start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": 500,
    })

    try:
        data = fetch_json("https://api.weather.gov/stations/KNYC/observations?" + params)
        peak = None

        for f in data.get("features", []):
            props = f.get("properties", {})
            raw_temp = props.get("temperature", {}).get("value")
            timestamp = parse_utc(props.get("timestamp"))
            if raw_temp is None or timestamp is None:
                continue

            local_time = timestamp.astimezone(TZ)
            if local_time.date() != now_local.date():
                continue

            temp = temp_f(raw_temp)
            if temp is None:
                continue

            if peak is None or temp > peak["temperature"]:
                peak = {
                    "temperature": temp,
                    "time": fmt_time(local_time),
                    "timestamp": timestamp.isoformat(),
                    "description": props.get("textDescription"),
                }

        if peak is None:
            return {"temperature": None, "time": None, "timestamp": None, "description": None}
        return peak
    except Exception as e:
        print("KNYC peak error:", e)
        return {"temperature": None, "time": None, "timestamp": None, "description": None}


def get_model(model_id):
    params = urlencode({
        "latitude": LAT,
        "longitude": LON,
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "UTC",
        "forecast_days": 3,
        "models": model_id,
    })
    url = "https://api.open-meteo.com/v1/forecast?" + params
    try:
        data = fetch_json(url)
        h = data.get("hourly", {})
        out = {}
        for ts, value in zip(h.get("time", []), h.get("temperature_2m", [])):
            dt = parse_utc(ts)
            if dt:
                out[dt.strftime("%Y-%m-%dT%H:00:00Z")] = clean_temp(value)
        print(model_id, "values:", len(out))
        return out
    except Exception as e:
        print("Model error", model_id, ":", e)
        return {}


def make_weather():
    now = datetime.now(timezone.utc)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    actual = get_knyc_actual()
    nws_peak = get_knyc_peak_today()

    model_data = {name: get_model(model_id) for name, model_id in MODELS.items()}

    hours = []
    for i in range(72):
        dt = current_hour + timedelta(hours=i)
        key = dt.strftime("%Y-%m-%dT%H:00:00Z")
        local = dt.astimezone(TZ)
        vals = {name: model_data[name].get(key) for name in MODELS}
        valid = [v for v in vals.values() if v is not None]
        hours.append({
            "time": key,
            "localTime": fmt_time(local),
            "date": fmt_date(local),
            "localDate": local.strftime("%Y-%m-%d"),
            "models": vals,
            "consensus": med(valid),
            "min": min(valid) if valid else None,
            "max": max(valid) if valid else None,
            "count": len(valid),
        })

    current = hours[0]
    daily = {}
    for h in hours:
        day = h["localDate"]
        daily.setdefault(day, {"date": day, "displayDate": fmt_day(parse_utc(h["time"]).astimezone(TZ)), "hours": []})["hours"].append(h)

    peaks = []
    for day in sorted(daily):
        info = daily[day]
        model_peaks = {}
        for name in MODELS:
            candidates = [h for h in info["hours"] if h["models"].get(name) is not None]
            if candidates:
                peak = max(candidates, key=lambda h: h["models"][name])
                model_peaks[name] = {"temperature": peak["models"][name], "time": peak["localTime"]}
            else:
                model_peaks[name] = {"temperature": None, "time": None}
        peak_values = [x["temperature"] for x in model_peaks.values() if x["temperature"] is not None]
        consensus = med(peak_values)
        closest_time = None
        if consensus is not None and peak_values:
            candidates = [x for x in model_peaks.values() if x["temperature"] is not None]
            closest_time = min(candidates, key=lambda x: abs(x["temperature"] - consensus))["time"]
        peaks.append({
            "date": day,
            "displayDate": info["displayDate"],
            "models": model_peaks,
            "consensus": consensus,
            "time": closest_time,
            "count": len(peak_values),
        })

    return {
        "location": "Central Park, New York",
        "station": "KNYC",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "models": list(MODELS.keys()),
        "actual": actual,
        "nwsPeakToday": nws_peak,
        "current": {
            "consensus": current["consensus"],
            "min": current["min"],
            "max": current["max"],
            "count": current["count"],
            "models": current["models"],
        },
        "forecast": hours,
        "dailyPeaks": peaks,
    }


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Central Park Weather</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0b0b0b;color:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:900px;margin:auto;padding:18px}h1{font-size:25px;margin:0}.sub{color:#888;margin:5px 0 16px}.tabs{display:flex;gap:8px;margin-bottom:14px}.tab{flex:1;padding:13px;border:1px solid #292929;border-radius:12px;background:#151515;color:#888;font-weight:700}.tab.active{background:#303030;color:#fff}.pane{display:none}.pane.active{display:block}.card{background:#151515;border:1px solid #292929;border-radius:16px;padding:17px;margin-bottom:14px}.label{font-size:12px;letter-spacing:1.5px;color:#888;text-transform:uppercase}.big{font-size:58px;font-weight:750;margin:4px 0}.actual{font-size:17px}.actual b{color:#70cf97}.muted{color:#777;font-size:12px;margin-top:7px}.title{font-size:18px;font-weight:700;margin-bottom:12px}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px}.model{background:#101010;border:1px solid #282828;border-radius:12px;padding:12px}.model.actual{border-color:#315b45}.name{font-size:12px;color:#999}.value{font-size:24px;font-weight:700;margin-top:4px}.history{display:grid;grid-template-columns:1fr 1fr;gap:9px}.hist{background:#101010;border-radius:12px;padding:13px}.hist .v{font-size:27px;font-weight:700}.hist .l{font-size:11px;color:#777}.row{border-top:1px solid #262626;padding:12px 0}.row:first-child{border-top:0}.rowtop{display:flex;justify-content:space-between;align-items:center}.time{font-weight:650}.date{font-size:11px;color:#666;margin-top:2px}.cons{font-size:23px;font-weight:750}.vals{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:7px}.sm{font-size:10px;color:#777}.sm b{font-size:12px;color:#bbb}.peak{background:#151515;border:1px solid #292929;border-radius:16px;padding:17px;margin-bottom:13px}.peakdate{font-size:19px;font-weight:700}.peakcons{font-size:47px;font-weight:750;margin-top:5px}.peakgrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:13px}.pmodel{background:#101010;border-radius:10px;padding:10px}.pname{font-size:10px;color:#777}.pvalue{font-size:20px;font-weight:700;margin-top:2px}.ptime{font-size:10px;color:#666}.note{font-size:12px;color:#777;line-height:1.55}.refresh{width:100%;border:0;border-radius:12px;padding:14px;background:#292929;color:#fff;font-weight:700;font-size:15px}@media(min-width:700px){.grid{grid-template-columns:repeat(3,1fr)}.vals{grid-template-columns:repeat(6,1fr)}.peakgrid{grid-template-columns:repeat(3,1fr)}}
</style>
</head>
<body>
<div class="wrap">
<h1>Central Park Weather</h1>
<div class="sub">KNYC • Six-Model Temperature Consensus</div>
<div class="tabs"><button class="tab active" onclick="tab('current',this)">Current</button><button class="tab" onclick="tab('peaks',this)">Daily Peak</button></div>
<div id="current" class="pane active">
<div class="card"><div class="label">Current Model Consensus</div><div class="big" id="cons">—</div><div class="actual" id="act">KNYC actual: —</div><div class="muted" id="spread">Model spread: —</div><div class="muted" id="upd">Loading...</div></div>
<div class="card"><div class="title">Current Model Temperatures</div><div id="models" class="grid"></div></div>
<div class="card"><div class="title">NWS Peak Today — KNYC</div><div class="history"><div class="hist"><div class="l">PEAK TEMPERATURE</div><div class="v" id="nwsPeak">—</div></div><div class="hist"><div class="l">TIME FOUND</div><div class="v" id="nwsPeakTime">—</div></div></div><div class="muted" id="nwsPeakDesc">Highest temperature observed by NWS at KNYC today.</div></div>
<div class="card"><div class="title">Next 24 Hours</div><div id="forecast">Loading...</div></div>
</div>
<div id="peaks" class="pane"><div class="card"><div class="title">Predicted Daily Peak Temperature</div><div class="note">For each local calendar day, every model's highest hourly forecast is calculated first. The displayed daily consensus is the median of those model peak temperatures.</div></div><div id="daily">Loading...</div></div>
<div class="card"><div class="title">Data Notes</div><div class="note">Models: ECMWF IFS, ECMWF AIFS, NBM, NAM, HRRR and GFS. The consensus is the median of available model values at the same hour. KNYC actual is the latest National Weather Service observation. AIFS has native 6-hourly output and may be interpolated to hourly resolution by Open-Meteo. NBM is a blended model, so the six forecasts are not statistically independent.</div></div>
<button class="refresh" onclick="load()">Refresh Weather</button>
</div>
<script>
const names={"ECMWF IFS":"IFS","ECMWF AIFS":"AIFS","NBM":"NBM","NAM":"NAM","HRRR":"HRRR","GFS":"GFS"};
function tab(id,b){document.querySelectorAll('.pane').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');b.classList.add('active')}
function t(v){return v===null||v===undefined?'—':Number(v).toFixed(1)+'°F'}
async function load(){
try{
 const r=await fetch('/api/weather?x='+Date.now(),{cache:'no-store'}); if(!r.ok)throw Error('HTTP '+r.status); const d=await r.json();
 document.getElementById('cons').textContent=t(d.current.consensus);document.getElementById('act').innerHTML='KNYC actual: <b>'+t(d.actual.temperature)+'</b>';document.getElementById('spread').textContent=d.current.min!==null?'Model spread: '+t(d.current.min)+' – '+t(d.current.max):'Model spread: —';document.getElementById('upd').textContent='Updated '+new Date(d.updatedAt).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
 let m='<div class="model actual"><div class="name">KNYC ACTUAL</div><div class="value">'+t(d.actual.temperature)+'</div></div>';for(const n of d.models)m+='<div class="model"><div class="name">'+n+'</div><div class="value">'+t(d.current.models[n])+'</div></div>';document.getElementById('models').innerHTML=m;
 document.getElementById('nwsPeak').textContent=t(d.nwsPeakToday.temperature);document.getElementById('nwsPeakTime').textContent=d.nwsPeakToday.time||'—';document.getElementById('nwsPeakDesc').textContent=d.nwsPeakToday.description?('NWS reported '+d.nwsPeakToday.description.toLowerCase()+' at the peak observation.'):'Highest temperature observed by NWS at KNYC today.';
 let f='';d.forecast.slice(0,24).forEach(h=>{let v='';for(const n of d.models)v+='<div class="sm">'+names[n]+'<br><b>'+t(h.models[n])+'</b></div>';f+='<div class="row"><div class="rowtop"><div><div class="time">'+h.localTime+'</div><div class="date">'+h.date+'</div></div><div class="cons">'+t(h.consensus)+'</div></div><div class="vals">'+v+'</div><div class="muted">'+h.count+'/6 models available</div></div>'});document.getElementById('forecast').innerHTML=f;
 let p='';d.dailyPeaks.slice(0,3).forEach((day,i)=>{let title=day.displayDate+(i===0?' • Today':i===1?' • Tomorrow': ' • Day After');let v='';for(const n of d.models){const x=day.models[n];v+='<div class="pmodel"><div class="pname">'+n+'</div><div class="pvalue">'+t(x.temperature)+'</div><div class="ptime">'+(x.time||'—')+'</div></div>'}p+='<div class="peak"><div class="peakdate">'+title+'</div><div class="peakcons">'+t(day.consensus)+'</div><div class="muted">Consensus peak around '+(day.time||'—')+'</div><div class="peakgrid">'+v+'</div><div class="muted">'+day.count+'/6 models available</div></div>'});document.getElementById('daily').innerHTML=p;
}catch(e){console.error(e);document.getElementById('upd').textContent='Update failed: '+e.message;document.getElementById('cons').textContent='—'}
}
load();setInterval(load,300000);
</script>
</body>
</html>'''


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, content_type="text/html; charset=utf-8", status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/weather":
            try:
                self.reply(json.dumps(make_weather()), "application/json; charset=utf-8")
            except Exception as e:
                print("API ERROR:", repr(e))
                self.reply(json.dumps({"error": str(e)}), "application/json; charset=utf-8", 500)
        else:
            self.reply(HTML)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    print("Central Park Weather server starting on port", PORT)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
