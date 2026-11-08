"""Probe: what Himawari-9 products NOAA's open bucket has, and how soon after the scan the newest files appear."""
import datetime as dt, re, urllib.request
B = 'https://noaa-himawari9.s3.amazonaws.com/'
def ls(prefix, delim=True):
    url = B + '?list-type=2&prefix=' + prefix + ('&delimiter=/' if delim else '')
    x = urllib.request.urlopen(url, timeout=30).read().decode()
    return re.findall(r'<Prefix>([^<]+)</Prefix>', x)[1:], re.findall(r'<Key>([^<]+)</Key><LastModified>([^<]+)</LastModified><ETag>[^<]*</ETag><Size>(\d+)', x)
print('top:', ls('')[0])
now = dt.datetime.utcnow()
for prod in [p for p in ls('')[0]]:
    day = now.strftime('%Y/%m/%d/')
    sub, _ = ls(prod + day)
    if not sub: print(prod, 'nothing today'); continue
    last = sub[-1]
    _, keys = ls(last, False)
    print('\n', prod, 'newest', last, 'now', now.strftime('%H:%M'), len(keys), 'files')
    for k, lm, sz in keys[:6] + [x for x in keys if 'B13' in x[0]][:12]:
        print('   ', k.split('/')[-1], lm, sz)
