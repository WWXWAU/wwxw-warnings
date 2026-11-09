"""Probe: which BoM WA forecast file has the weather situation (synoptic) text."""
import urllib.request, re
ls = urllib.request.urlopen('ftp://ftp.bom.gov.au/anon/gen/fwo/', timeout=60).read().decode('utf-8', 'replace')
names = sorted(set(re.findall(r'(IDW1\d{4}\.xml)', ls)))
print(len(names), 'WA forecast xml files')
for n in names:
    try:
        x = urllib.request.urlopen('ftp://ftp.bom.gov.au/anon/gen/fwo/' + n, timeout=60).read().decode('utf-8', 'replace')
    except Exception as e:
        continue
    t = re.search(r'<text type="synoptic_situation">(.*?)</text>', x, re.S)
    title = re.search(r'<product-type>|<title>([^<]*)', x)
    if t: print(n, len(x), '|', re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t.group(1)))[:500])
