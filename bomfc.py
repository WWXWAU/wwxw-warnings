"""
West WX Watchers — BoM town forecasts for the "Near you" card.

Reads the Bureau's WA précis forecasts (IDW14199.xml, the 7-day town forecasts) from the anonymous FTP server
(ftp.bom.gov.au/anon/gen/fwo) and the forecast locations' positions (IDM00013, the Bureau's forecast point places,
/anon/home/adfd/spatial), and writes data/bom-forecast.json:
  {"issued": ..., "source": ..., "places": [{"n": "Perth", "a": "WA_PT053", "lat": .., "lng": ..,
     "days": [{"d": "2026-11-23", "i": 3, "lo": 14, "hi": 27, "t": "Partly cloudy.", "p": "20%", "r": "0 to 1 mm"}]}]}
Written only when the Bureau issues a new forecast. Positions are kept in data/bom-places.json (fetched once a week).
"""
import ftplib, io, json, os, struct, sys, time, datetime as dt
import xml.etree.ElementTree as ET

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
OUT, POS = os.path.join(DATA, 'bom-forecast.json'), os.path.join(DATA, 'bom-places.json')


def log(*a):
    print(*a, flush=True)


def ftp_get(folder, name):
    for attempt in range(3):
        try:
            f = ftplib.FTP('ftp.bom.gov.au', timeout=60); f.login(); f.cwd(folder)
            buf = io.BytesIO(); f.retrbinary('RETR ' + name, buf.write); f.quit()
            return buf.getvalue()
        except Exception as e:
            log('FTP', folder + '/' + name, 'try', attempt + 1, e); time.sleep(5)
    return None


def read_dbf(raw):
    """A plain dBase III reader: list of dicts."""
    n, hlen, rlen = struct.unpack('<xxxxLHH', raw[:12])
    fields, p = [], 32
    while raw[p] != 0x0D:
        name = raw[p:p + 11].split(b'\0')[0].decode('latin-1'); fields.append((name, raw[p + 16])); p += 32
    out = []
    for i in range(n):
        r = raw[hlen + i * rlen: hlen + (i + 1) * rlen]
        if not r or r[0:1] == b'*': continue
        q, rec = 1, {}
        for name, ln in fields:
            rec[name] = r[q:q + ln].decode('latin-1').strip(); q += ln
        out.append(rec)
    return out


def positions():
    have = json.load(open(POS)) if os.path.exists(POS) else None
    if have and time.time() - have.get('t', 0) < 7 * 86400 and have.get('p'):
        return have['p']
    raw = ftp_get('/anon/home/adfd/spatial', 'IDM00013.dbf')
    if not raw:
        return have['p'] if have else {}
    p = {}
    for r in read_dbf(raw):
        aac = r.get('AAC') or r.get('aac')
        try:
            lat, lng = float(r.get('LAT') or r.get('lat')), float(r.get('LON') or r.get('lon'))
        except (TypeError, ValueError):
            continue
        if aac and aac.startswith('WA_'):
            p[aac] = [round(lat, 4), round(lng, 4)]
    log('Forecast places with positions:', len(p))
    if p:
        json.dump({'t': int(time.time()), 'source': 'Bureau of Meteorology IDM00013', 'p': p}, open(POS, 'w'), separators=(',', ':'))
    return p


def main():
    raw = ftp_get('/anon/gen/fwo', 'IDW14199.xml')
    if not raw:
        log('No forecast file.'); return
    root = ET.fromstring(raw)
    issued = (root.findtext('.//issue-time-utc') or '').strip()
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if prev.get('issued') == issued and '--force' not in sys.argv:
        log('Forecast unchanged (issued', issued + ').'); return
    pos = positions()
    places = []
    for area in root.iter('area'):
        if area.get('type') != 'location': continue
        aac = area.get('aac'); xy = pos.get(aac)
        if not xy: continue
        days = []
        for fp in area.findall('forecast-period'):
            d = {'d': (fp.get('start-time-local') or '')[:10]}
            for el in fp:
                ty, v = el.get('type'), (el.text or '').strip()
                if ty == 'forecast_icon_code': d['i'] = int(v) if v.isdigit() else None
                elif ty == 'air_temperature_minimum': d['lo'] = int(float(v))
                elif ty == 'air_temperature_maximum': d['hi'] = int(float(v))
                elif ty == 'precis': d['t'] = v
                elif ty == 'probability_of_precipitation': d['p'] = v
                elif ty == 'precipitation_range': d['r'] = v
            days.append(d)
        if days:
            places.append({'n': area.get('description'), 'a': aac, 'lat': xy[0], 'lng': xy[1], 'days': days})
    if not places:
        log('No forecast places matched positions; not written.'); return
    json.dump({'issued': issued, 'source': 'Bureau of Meteorology (ftp.bom.gov.au/anon/gen/fwo/IDW14199.xml)',
               'places': places}, open(OUT, 'w'), separators=(',', ':'))
    log('Forecast written:', len(places), 'places, issued', issued)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log('BoM forecast failed:', e)
