"""Download EWN's significant weather map; say whether it changed since the last one we kept."""
import hashlib, json, os, urllib.request, datetime

URL = 'https://alerts3.ewn.com.au/threat_maps/significant_weather_large.png'
STATE = 'data/ewn/state.json'

req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (wwxw reference check)'})
with urllib.request.urlopen(req, timeout=60) as r:
    img, lastmod = r.read(), r.headers.get('Last-Modified', '')
h = hashlib.sha256(img).hexdigest()
state = json.load(open(STATE)) if os.path.exists(STATE) else {}
now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
stamp = now.strftime('%Y%m%d-%H%M')
new = h != state.get('hash')
print(f'{len(img)} bytes, Last-Modified {lastmod or "?"}, {"NEW" if new else "same as " + state.get("seen", "?")}')
if new:
    os.makedirs('ewn-tmp', exist_ok=True)
    open(f'ewn-tmp/ewn-{stamp}.png', 'wb').write(img)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({'hash': h, 'seen': now.strftime('%Y-%m-%d %H:%M'), 'last_modified': lastmod, 'bytes': len(img)}, open(STATE, 'w'), indent=1)
with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as o:
    o.write(f'new={1 if new else 0}\nstamp={stamp}\n')
