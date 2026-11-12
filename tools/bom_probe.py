"""Probe: the Bureau's official forecast grids for WA (ADFD, IDW71xxx GRIB2 on the public FTP): which fields there are,
and whether any is a thunderstorm field."""
import urllib.request, re
ls = urllib.request.urlopen('ftp://ftp.bom.gov.au/anon/gen/fwo/', timeout=60).read().decode('utf-8', 'replace')
rows = [l for l in ls.splitlines() if re.search(r'IDW7\d{4}', l)]
print(len(rows), 'WA grid files')
for l in rows: print(l)
for l in ls.splitlines():
    if re.search(r'thund|storm|wx|weather|_Wx', l, re.I) and 'IDW7' not in l: print('other:', l)
