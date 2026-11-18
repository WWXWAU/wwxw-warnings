"""Probe: can we download Google Weather Lab's past cyclone forecasts and IBTrACS best tracks?"""
import urllib.request, sys
def get(u, n=600):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 WWXW'}), timeout=60)
        b = r.read(); print('OK', r.status, len(b), u); print(b[:n].decode('utf-8', 'replace')); return b
    except Exception as e:
        print('FAIL', u, e); return None
G = 'https://deepmind.google.com/science/weatherlab/download/cyclones/'
for m in ['OPER', 'FNV3', 'GENC', 'FNV2', 'WN2C']:
    for d in ['2025_03_01T00_00', '2024_02_01T00_00', '2023_12_01T00_00']:
        get(G + m + '/ensemble_mean/paired/atcf/' + m + '_' + d + '_atcf_a_deck.txt', 400)
get(G)
get('https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/ibtracs.SI.list.v04r01.csv', 300)
