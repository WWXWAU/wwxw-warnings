"""Probe: the layout of NOAA's Himawari-9 ISatSS band-13 tiles."""
import datetime as dt, re, urllib.request, h5py, io, numpy as np
B = 'https://noaa-himawari9.s3.amazonaws.com/'
def ls(prefix, delim=True):
    url = B + '?list-type=2&prefix=' + prefix + ('&delimiter=/' if delim else '')
    x = urllib.request.urlopen(url, timeout=30).read().decode()
    return re.findall(r'<Prefix>([^<]+)</Prefix>', x)[1:], re.findall(r'<Key>([^<]+)</Key>.*?<LastModified>([^<]+)</LastModified>.*?<Size>(\d+)', x)
now = dt.datetime.utcnow(); day = now.strftime('%Y/%m/%d/')
sub, _ = ls('AHI-L2-FLDK-ISatSS/' + day)
c13 = []
for f in sub[-8:]:
    for k, lm, sz in ls(f, False)[1]:
        if '-M1C13-' in k: c13.append((k, lm, sz))
for k, lm, sz in c13: print(k.split('/')[-2], k.split('/')[-1][:60], lm[11:19], sz)
k = c13[-1][0]
f = h5py.File(io.BytesIO(urllib.request.urlopen(B + k, timeout=60).read()), 'r')
def show(name, o):
    print(name, getattr(o, 'shape', ''), getattr(o, 'dtype', ''), {a: (o.attrs[a][:5] if hasattr(o.attrs[a], '__len__') and not isinstance(o.attrs[a], (bytes, str)) else o.attrs[a]) for a in list(o.attrs)[:40]})
show('/', f)
f.visititems(show)
