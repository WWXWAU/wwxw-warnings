"""Temporary: does the current 10-minute Blitzortung file grow while the 10 minutes are running? (prints sizes only)"""
import base64, datetime as dt, json, os, time, urllib.request, urllib.error
BASE = 'https://data.blitzortung.org/Data/Protected/Strikes_2/'
AUTH = 'Basic ' + base64.b64encode(('%s:%s' % (os.environ['BLITZ_USER'], os.environ['BLITZ_PASS'])).encode()).decode()
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={'Authorization': AUTH}), timeout=60) as r:
            return r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return None, {'code': e.code}
end = time.time() + 14 * 60
while time.time() < end:
    now = dt.datetime.utcnow()
    for back in (0, 10):
        t = now - dt.timedelta(minutes=back)
        slot = t.replace(minute=t.minute - t.minute % 10, second=0, microsecond=0)
        b, h = get(BASE + slot.strftime('%Y/%m/%d/%H/%M') + '.json')
        if b is None:
            print('%s slot %s: %s' % (now.strftime('%H:%M:%S'), slot.strftime('%H:%M'), h), flush=True); continue
        lines = [l for l in b.decode('utf-8', 'replace').splitlines() if l.startswith('{')]
        newest = max((json.loads(l)['time'] for l in lines), default=0) / 1e9
        print('%s slot %s: %d bytes, %d strikes, newest strike %.0f s ago, Last-Modified %s' % (
            now.strftime('%H:%M:%S'), slot.strftime('%H:%M'), len(b), len(lines), time.time() - newest if newest else -1, h.get('Last-Modified')), flush=True)
    time.sleep(30)
