"""Probe: JTWC's RSS list of current products, and one warning's text."""
import re, urllib.request
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 westwxwatchers'}), timeout=40).read().decode('utf-8', 'replace')
rss = get('https://www.metoc.navy.mil/jtwc/rss/jtwc.rss')
print(rss[:3000])
links = sorted(set(re.findall(r'https?://[^"<\s]+web\.txt', rss)))
print('LINKS', links)
for u in links[:3]:
    print('=====', u); print(get(u)[:2500])
