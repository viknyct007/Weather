import json
import os
import statistics
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

HOST = '0.0.0.0'
PORT = int(os.environ.get('PORT', '10000'))
NWS = 'https://api.weather.gov'
OM = 'https://api.open-meteo.com/v1/forecast'
UA = 'MultiStationWeather/1.0 (weather dashboard)'

STATIONS = {
    'KLAX': {'name':'Los Angeles International Airport','lat':33.9425,'lon':-118.4081,'tz':'America/Los_Angeles'},
    'KMIA': {'name':'Miami International Airport','lat':25.7959,'lon':-80.2870,'tz':'America/New_York'},
    'KSFO': {'name':'San Francisco International Airport','lat':37.6213,'lon':-122.3790,'tz':'America/Los_Angeles'},
    'KMDW': {'name':'Chicago Midway International Airport','lat':41.7868,'lon':-87.7522,'tz':'America/Chicago'},
}

MODELS = {
    'ECMWF IFS':'ecmwf_ifs',
    'ECMWF AIFS':'ecmwf_aifs025_single',
    'GFS':'ncep_gfs_global',
    'HRRR':'ncep_hrrr_conus',
    'NBM':'ncep_nbm_conus',
    'NAM':'ncep_nam_conus',
}


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent':UA, 'Accept':'application/json,application/geo+json'})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode('utf-8'))


def parse_utc(value):
    if not value: return None
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone.utc)


def key(dt):
    return dt.isoformat().replace('+00:00','Z')


def median(values):
    values = [float(v) for v in values if v is not None]
    return round(statistics.median(values),1) if values else None


def c_to_f(v):
    return None if v is None else round(float(v)*9/5+32,1)


def get_nws(station_id, s):
    point = get_json(f"{NWS}/points/{s['lat']},{s['lon']}")['properties']
    periods = get_json(point['forecastHourly'])['properties']['periods']
    try:
        obs = get_json(f"{NWS}/stations/{station_id}/observations/latest")['properties']
    except Exception:
        stations = get_json(point['observationStations'])['features']
        sid = stations[0]['properties']['stationIdentifier']
        obs = get_json(f"{NWS}/stations/{sid}/observations/latest")['properties']
    hourly = {}
    for p in periods:
        dt = parse_utc(p.get('startTime'))
        if dt is not None and p.get('temperature') is not None:
            hourly[key(dt)] = float(p['temperature'])
    return hourly, {
        'temperature': c_to_f(obs.get('temperature',{}).get('value')),
        'description': obs.get('textDescription','NWS observation unavailable'),
        'time': obs.get('timestamp')
    }


def get_model(s, model_id):
    params = {
        'latitude':s['lat'],'longitude':s['lon'],
        'hourly':'temperature_2m','temperature_unit':'fahrenheit',
        'timezone':'UTC','forecast_days':4,'models':model_id
    }
    try:
        data = get_json(OM+'?'+urllib.parse.urlencode(params))
        out = {}
        for t,v in zip(data.get('hourly',{}).get('time',[]), data.get('hourly',{}).get('temperature_2m',[])):
            if v is not None:
                out[key(datetime.fromisoformat(t).replace(tzinfo=timezone.utc))] = round(float(v),1)
        return out
    except Exception:
        return {}


def build_station(station_id, s):
    nws_hours, current = get_nws(station_id,s)
    models = {}
    with ThreadPoolExecutor(max_workers=len(MODELS)) as ex:
        jobs = {ex.submit(get_model,s,mid):name for name,mid in MODELS.items()}
        for job in as_completed(jobs):
            name = jobs[job]
            try: models[name] = job.result()
            except Exception: models[name] = {}

    now = datetime.now(timezone.utc)
    times = set(nws_hours)
    for m in models.values(): times.update(m)
    future = [t for t in sorted(times) if (parse_utc(t) or now) >= now][:72]

    hourly = []
    for t in future[:24]:
        vals = {name:models.get(name,{}).get(t) for name in MODELS}
        hourly.append({'time':t,'nws':nws_hours.get(t),'models':vals,'consensus':median(vals.values())})

    days = {}
    for t in future:
        local = parse_utc(t).astimezone(ZoneInfo(s['tz']))
        d = local.date().isoformat()
        b = days.setdefault(d, {'nws':[],'models':{name:[] for name in MODELS}})
        if nws_hours.get(t) is not None: b['nws'].append(nws_hours[t])
        for name in MODELS:
            v = models.get(name,{}).get(t)
            if v is not None: b['models'][name].append(v)

    daily=[]
    for d in sorted(days)[:3]:
        b=days[d]
        mx={name:(round(max(v),1) if v else None) for name,v in b['models'].items()}
        daily.append({'date':d,'nws_max':round(max(b['nws']),1) if b['nws'] else None,'model_max':mx,'consensus_max':median(mx.values())})

    return {'name':s['name'],'timezone':s['tz'],'current':current,'hourly_24':hourly,'daily_3':daily}


HTML = """<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Multi-Station Weather</title><style>
*{box-sizing:border-box}body{margin:0;background:#0b0f14;color:#f3f5f7;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}header{padding:20px 16px;border-bottom:1px solid #28313b}.wrap{max-width:1150px;margin:auto;padding:16px}h1{margin:0 0 5px;font-size:24px}.sub,.small,.muted{color:#94a1ad}.tabs{display:flex;gap:8px;overflow:auto;margin-bottom:14px}.tab{border:1px solid #34404c;background:#121820;color:#d0d7de;padding:10px 15px;border-radius:10px}.tab.active{background:#edf1f4;color:#101419}.card{background:#111720;border:1px solid #28323d;border-radius:14px;padding:15px;margin:12px 0}.card h2{margin:0 0 12px;font-size:18px}.now{display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap}.big{font-size:42px;font-weight:700}.badges{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.badge{border:1px solid #35414c;border-radius:999px;padding:5px 8px;font-size:11px;color:#bac4cd}.scroll{overflow:auto}table{width:100%;min-width:900px;border-collapse:collapse;font-size:13px}th,td{padding:9px 7px;border-bottom:1px solid #222c35;text-align:left;white-space:nowrap}th{color:#9da9b4;background:#111720}button{font:inherit;cursor:pointer}#refresh{background:#17212b;border:1px solid #36424e;color:white;border-radius:9px;padding:9px 13px}.error{color:#ff9b9b}
</style></head><body><header><div class='wrap' style='padding:0'><h1>Multi-Station Weather Forecast</h1><div class='sub'>NWS + ECMWF + NOAA/NCEP models · refreshes every 5 minutes</div></div></header><div class='wrap'><div id='tabs' class='tabs'></div><div id='app'><div class='card'>Loading...</div></div><button id='refresh'>Refresh now</button><div id='updated' class='small' style='margin-top:10px'></div></div>
<script>
let data=null;const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const temp=v=>v==null?'—':Number(v).toFixed(1)+'°F';
function lt(v,tz){if(!v)return'—';return new Date(v).toLocaleString([],{timeZone:tz,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}
function render(){const ids=Object.keys(data.stations);document.getElementById('tabs').innerHTML=ids.map((id,i)=>`<button class='tab ${i?'':'active'}' onclick="selectStation('${id}',this)">${id}</button>`).join('');show(ids[0]);document.getElementById('updated').textContent='Last updated: '+new Date(data.fetched_at).toLocaleString()}
function selectStation(id,b){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');show(id)}
function show(id){const s=data.stations[id],names=Object.keys(data.model_names);const hr=s.hourly_24.map(r=>`<tr><td>${lt(r.time,s.timezone)}</td><td>${temp(r.nws)}</td>${names.map(n=>`<td>${temp(r.models[n])}</td>`).join('')}<td><b>${temp(r.consensus)}</b></td></tr>`).join('');const dy=s.daily_3.map(r=>`<tr><td>${r.date}</td><td>${temp(r.nws_max)}</td>${names.map(n=>`<td>${temp(r.model_max[n])}</td>`).join('')}<td><b>${temp(r.consensus_max)}</b></td></tr>`).join('');document.getElementById('app').innerHTML=`<div class='card'><h2>${esc(id)} — ${esc(s.name)}</h2><div class='now'><div><div class='big'>${temp(s.current.temperature)}</div><div>${esc(s.current.description)}</div></div><div class='muted'>NWS observation<br>${lt(s.current.time,s.timezone)}</div></div><div class='badges'><span class='badge'>NWS</span>${names.map(n=>`<span class='badge'>${esc(n)}</span>`).join('')}<span class='badge'>Median consensus</span></div></div><div class='card'><h2>Next 24 Hours — Hourly Prediction</h2><div class='scroll'><table><thead><tr><th>Time</th><th>NWS</th>${names.map(n=>`<th>${esc(n)}</th>`).join('')}<th>Consensus</th></tr></thead><tbody>${hr}</tbody></table></div></div><div class='card'><h2>3-Day Maximum Temperature Prediction</h2><div class='scroll'><table><thead><tr><th>Date</th><th>NWS</th>${names.map(n=>`<th>${esc(n)}</th>`).join('')}<th>Consensus</th></tr></thead><tbody>${dy}</tbody></table></div></div><div class='card'><h2>Sources</h2><div class='small'>NWS official hourly forecast and airport observation; ECMWF IFS; ECMWF AIFS; NOAA/NCEP GFS; HRRR; NBM; NAM. Every source is shown separately. Consensus is the median of available model predictions.</div></div>`}
async function load(){document.getElementById('app').innerHTML='<div class="card">Updating...</div>';try{const r=await fetch('/api/weather?x='+Date.now());if(!r.ok)throw Error(await r.text());data=await r.json();render()}catch(e){document.getElementById('app').innerHTML='<div class="card error">Weather update failed: '+esc(e.message)+'</div>'}}document.getElementById('refresh').onclick=load;load();setInterval(load,300000);
</script></body></html>"""


def build_all():
    out={}
    with ThreadPoolExecutor(max_workers=4) as ex:
        jobs={ex.submit(build_station,code,s):code for code,s in STATIONS.items()}
        for job in as_completed(jobs):
            code=jobs[job]
            try: out[code]=job.result()
            except Exception as e:
                s=STATIONS[code];out[code]={'name':s['name'],'timezone':s['tz'],'current':{'temperature':None,'description':'Unable to load station','time':None},'hourly_24':[],'daily_3':[],'error':str(e)}
    return {k:out[k] for k in STATIONS}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/api/weather'):
            try:
                body=json.dumps({'fetched_at':datetime.now(timezone.utc).isoformat(),'model_names':MODELS,'stations':build_all()}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
            except Exception as e:
                body=json.dumps({'error':str(e)}).encode();self.send_response(500);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        else:
            body=HTML.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    def log_message(self,fmt,*args): print(fmt%args)

if __name__=='__main__':
    print(f'Listening on {HOST}:{PORT}')
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
