"""Download EWN's significant weather map; if it is a new map for today (AWST), read it into WA reference areas.

Writes data/ewn/<date>.json (areas) and data/ewn/<date>.png (our own drawing of what was traced).
EWN's picture itself is never committed.
"""
import datetime, glob, hashlib, json, os, sys, urllib.request
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(__file__))
import extract

URL = 'https://alerts3.ewn.com.au/threat_maps/significant_weather_large.png'
STATE = 'data/ewn/state.json'
AWST = datetime.timezone(datetime.timedelta(hours=8))

req = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 (wwxw reference check)'})
with urllib.request.urlopen(req, timeout=60) as r:
    img, lastmod = r.read(), r.headers.get('Last-Modified', '')
now = datetime.datetime.now(AWST)
today = now.strftime('%Y-%m-%d')
h = hashlib.sha256(img).hexdigest()
state = json.load(open(STATE)) if os.path.exists(STATE) else {}
new = h != state.get('hash') or os.environ.get('FORCE') == '1'
lm = parsedate_to_datetime(lastmod).astimezone(AWST) if lastmod else None
# a map counts for today if it was published today after 5 am AWST
fresh = lm is not None and lm.strftime('%Y-%m-%d') == today and lm.hour >= 5
print(f'{len(img)} bytes, Last-Modified {lm.strftime("%Y-%m-%d %H:%M AWST") if lm else "?"}, ' +
      ('new' if new else 'unchanged') + ', ' + ("today's map" if fresh else "not today's map yet"))

os.makedirs('ewn-tmp', exist_ok=True)
stamp = now.strftime('%Y%m%d-%H%M')
path = f'ewn-tmp/ewn-{stamp}.png'
open(path, 'wb').write(img)
read = '0'
if new and fresh:
    im, res, masks = extract.extract(path)
    res.update({'date': today, 'seen': now.strftime('%Y-%m-%d %H:%M'), 'published': lm.strftime('%Y-%m-%d %H:%M')})
    json.dump(res, open(f'data/ewn/{today}.json', 'w'))
    extract.preview(im, masks, f'data/ewn/{today}.png')
    print('areas:', json.dumps(res['px']), '| storm areas', len(res['storms']), '| severe areas', len(res['severe']))
    read = '1'
    # keep 60 days of pictures (the areas themselves are tiny and stay)
    for f in sorted(glob.glob('data/ewn/20*.png'))[:-60]:
        os.remove(f)
if new:
    json.dump({'hash': h, 'seen': now.strftime('%Y-%m-%d %H:%M'), 'last_modified': lastmod, 'bytes': len(img)}, open(STATE, 'w'), indent=1)
with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as o:
    o.write(f'new={1 if new else 0}\nread={read}\nstamp={stamp}\n')
