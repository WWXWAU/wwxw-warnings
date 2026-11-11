"""Probe 31: Port Hedland's (and Iron Bridge's) BoM record around the 146 km/h gust on 10 Nov."""
import sys, json
sys.path.insert(0, 'rivers'); import rivers as RV
for sid in ('94312', '95316', '94316'):
    for host in ('reg.bom.gov.au', 'www.bom.gov.au'):
        try:
            d = json.loads(RV.get('http://%s/fwo/IDW60801/IDW60801.%s.json' % (host, sid), 60, 2)); break
        except Exception as e: print(sid, host, e); d = None
    if not d: continue
    obs = d['observations']['data']; print('\n==', obs[0]['name'], len(obs))
    for o in sorted(obs, key=lambda o: o['local_date_time_full']):
        if '20261110150000' <= o['local_date_time_full'] <= '20261110220000':
            print(o['local_date_time_full'][8:12], 'wind', o.get('wind_spd_kmh'), 'gust', o.get('gust_kmh'), o.get('wind_dir'), 'T', o.get('air_temp'), 'rain', o.get('rain_trace'), 'p', o.get('press'))
