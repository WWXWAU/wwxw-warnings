"""Probe: NOAA's Himawari-9 ISatSS files - names, sizes, times."""
import datetime as dt, re, urllib.request
B = 'https://noaa-himawari9.s3.amazonaws.com/'
def ls(prefix, delim=True):
    url = B + '?list-type=2&prefix=' + prefix + ('&delimiter=/' if delim else '')
    x = urllib.request.urlopen(url, timeout=30).read().decode()
    return re.findall(r'<Prefix>([^<]+)</Prefix>', x)[1:], re.findall(r'<Key>([^<]+)</Key>.*?<LastModified>([^<]+)</LastModified>.*?<Size>(\d+)', x)
now = dt.datetime.utcnow(); day = now.strftime('%Y/%m/%d/')
for prod in ['AHI-L2-FLDK-ISatSS/', 'AHI-L2-FLDK-Clouds/']:
    sub, _ = ls(prod + day)
    print(prod, 'folders today:', len(sub), sub[-4:])
    _, keys = ls(sub[-1], False)
    print(' newest folder', sub[-1], 'now', now.strftime('%H:%M:%S'), len(keys), 'files')
    for k, lm, sz in keys[:40]: print('   ', k.split('/')[-1], lm, sz)
import sys
# header of one band-13 tile
k = [k for k, _, _ in ls(sub[-1], False)[1]]
