"""Probe: is the Bureau's thunderstorm forecast grid (ADFD WxThunderstorm, product 71094) on the public FTP?"""
import urllib.request, re
for d in ('anon/gen/adfd/', 'anon/gen/', 'anon/sample/catalogue/ADFD/', 'anon/gen/fwo/'):
    try:
        ls = urllib.request.urlopen('ftp://ftp.bom.gov.au/' + d, timeout=90).read().decode('utf-8', 'replace').splitlines()
    except Exception as e:
        print(d, 'not read:', e); continue
    hit = [l for l in ls if re.search(r'7\d{4}|thund|Wx|adfd|grib|\.nc', l, re.I)]
    print('==', d, len(ls), 'entries,', len(hit), 'grid-like')
    for l in (hit if d != 'anon/gen/' else ls)[:150]: print('  ', l)
