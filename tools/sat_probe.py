"""Probe: which ISatSS sectors exist (full disk?) and where their band-13 tiles sit."""
import datetime as dt, re, urllib.request, collections
B = 'https://noaa-himawari9.s3.amazonaws.com/'
def ls(prefix, delim=True, token=None):
    url = B + '?list-type=2&prefix=' + prefix + ('&delimiter=/' if delim else '') + ('&continuation-token=' + urllib.request.quote(token) if token else '')
    x = urllib.request.urlopen(url, timeout=30).read().decode()
    nxt = re.search(r'<NextContinuationToken>([^<]+)<', x)
    return re.findall(r'<Prefix>([^<]+)</Prefix>', x)[1:], re.findall(r'<Key>([^<]+)</Key>.*?<LastModified>([^<]+)</LastModified>.*?<Size>(\d+)', x), (nxt.group(1) if nxt else None)
now = dt.datetime.now(dt.timezone.utc); day = now.strftime('%Y/%m/%d/')
sub = ls('AHI-L2-FLDK-ISatSS/' + day)[0]
cnt = collections.Counter()
for f in sub[-14:]:
    keys, tok = [], None
    while True:
        _, k, tok = ls(f, False, tok); keys += k
        if not tok: break
    sect = collections.Counter(re.sub(r'-T\d+_.*', '', x[0].split('/')[-1]) for x in keys)
    print(f.split('/')[-2], len(keys), 'files', dict((s, n) for s, n in sect.items() if 'C13' in s or 'C03' in s))
    for k, lm, sz in keys:
        n = k.split('/')[-1]
        if 'C13' in n and 'HR3' not in n: cnt[re.sub(r'_GH9.*', '', n)] += 1
print(sorted(cnt.items())[:80])
