"""Exact positions of the Bureau's WA weather stations, by WMO number, from its public station list (anonymous FTP,
anon2/home/ncc/metadata/sitelists/stations.zip). The live observation files only give positions to 0.1° (up to ~6 km
out: Broome, Cape Naturaliste and Garden Island plotted in the sea). Writes data/bom-sites-wa.json:
{"94203": [lat, lng, "BROOME AIRPORT", site number], …}. Run monthly by .github/workflows/bom-sites.yml."""
import ftplib, io, json, os, re, zipfile
f = ftplib.FTP('ftp.bom.gov.au', timeout=120); f.login()
b = io.BytesIO(); f.retrbinary('RETR /anon2/home/ncc/metadata/sitelists/stations.zip', b.write)
z = zipfile.ZipFile(b); txt = z.read(z.namelist()[0]).decode('latin-1')
out = {}
for line in txt.splitlines():
    # Site  Dist  Site name  Start  End  Lat  Lon  Source  STA  Height (m)  Bar_ht  WMO
    m = re.match(r'^\s*(\d{4,6})\s+\S+\s+(.+?)\s+(\d{4}|\.\.)\s+(\d{4}|\.\.)\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s+\S.*?\s(WA|NT|SA|QLD|NSW|VIC|TAS|ANT|ISL)\s.*?(\d{5})?\s*$', line)
    if not m: continue
    site, name, end, lat, lng, sta, wmo = m.group(1), m.group(2).strip(), m.group(4), float(m.group(5)), float(m.group(6)), m.group(7), m.group(8)
    if not wmo or end != '..': continue                     # still open, and with a WMO number (the ones in the live files)
    if not (sta == 'WA' or (sta == 'ISL' and 90 < lng < 130)): continue
    out[wmo] = [round(lat, 4), round(lng, 4), name, int(site)]
print(len(out), 'open WA stations with WMO numbers; e.g.', {k: out[k] for k in list(out)[:3]})
for w in ('94203', '94610', '94617', '94303'): print(w, out.get(w))
os.makedirs('data', exist_ok=True)
json.dump(out, open('data/bom-sites-wa.json', 'w'), separators=(',', ':'), sort_keys=True)
