"""What makes up the Rainfall / Live Obs pages (Apps Script wraps the page as an escaped string)."""
import gzip, re, sys, urllib.request, codecs
R = 'https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec'
for name, url in (('rainfall', R), ('obs', R + '?page=obs')):
    raw = urllib.request.urlopen(url, timeout=90).read().decode('utf-8', 'replace')
    print('\n==', name, 'download', len(raw), 'bytes, gzipped', len(gzip.compress(raw.encode())))
    # the user HTML is inside a JS string: unescape \x3c and \u... roughly
    m = max(re.findall(r'"((?:[^"\\]|\\.){20000,})"', raw), key=len, default='')
    try: html = codecs.decode(m, 'unicode_escape')
    except Exception: html = m
    print('page html', len(html), 'gzipped', len(gzip.compress(html.encode('utf-8', 'replace'))))
    parts = {}
    for mm in re.finditer(r'data:[a-z/+]+;base64,[A-Za-z0-9+/=]{500,}', html): parts.setdefault('data: images', []).append(len(mm.group(0)))
    for mm in re.finditer(r'(var|const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*([\[{"\'])', html):
        start = mm.end() - 1; depth = 0; q = None; i = start
        if html[start] in '"\'':
            j = html.find(html[start], start + 1)
            while j > 0 and html[j - 1] == '\\': j = html.find(html[start], j + 1)
            size = j - start
        else:
            for i in range(start, min(len(html), start + 3_000_000)):
                ch = html[i]
                if q:
                    if ch == q and html[i - 1] != '\\': q = None
                elif ch in '"\'': q = ch
                elif ch in '[{': depth += 1
                elif ch in ']}':
                    depth -= 1
                    if depth == 0: break
            size = i - start
        if size > 8000: parts.setdefault('var ' + mm.group(2), []).append(size)
    for mm in re.finditer(r'<script>(.*?)</script>', html, re.S):
        if len(mm.group(1)) > 20000: parts.setdefault('script blocks >20k', []).append(len(mm.group(1)))
    for mm in re.finditer(r'<style>(.*?)</style>', html, re.S): parts.setdefault('styles', []).append(len(mm.group(1)))
    for k, v in sorted(parts.items(), key=lambda kv: -sum(kv[1])): print('  %-28s %8d bytes  (%d)' % (k, sum(v), len(v)))
    for mm in re.findall(r'<script src="([^"]+)"', html): print('  external script:', mm)
