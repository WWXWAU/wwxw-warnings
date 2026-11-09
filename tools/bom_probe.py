"""Probe: BoM WA state forecast (synoptic situation text)."""
import urllib.request, re
for pid in ('IDW12300', 'IDW12400', 'IDW10200'):
    url = 'ftp://ftp.bom.gov.au/anon/gen/fwo/%s.xml' % pid
    try:
        x = urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'replace')
        print('\nOK', pid, len(x), re.findall(r'<text type="([a-z_]+)"', x)[:20])
        for m in re.finditer(r'<text type="(synoptic_situation|forecast)">(.*?)</text>', x, re.S):
            print(' ', m.group(1), ':', re.sub(r'\s+', ' ', m.group(2))[:400]); 
    except Exception as e:
        print('FAIL', pid, e)
