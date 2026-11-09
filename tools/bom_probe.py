"""Probe: BoM WA town forecasts (IDW14199 precis XML) - can we fetch it, how many places, which fields."""
import urllib.request, re, collections
for url in ('ftp://ftp.bom.gov.au/anon/gen/fwo/IDW14199.xml', 'https://reg.bom.gov.au/fwo/IDW14199.xml'):
    try:
        x = urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'replace')
        print('OK', url, len(x))
        areas = re.findall(r'<area aac="([^"]+)" description="([^"]+)" type="location"', x)
        print(len(areas), 'locations, e.g.', [a[1] for a in areas[:25]])
        print('element types:', collections.Counter(re.findall(r'type="([a-z_]+)"', x)).most_common(20))
        i = x.find('description="Perth"'); print(x[i:i+1800])
        break
    except Exception as e:
        print('FAIL', url, e)
