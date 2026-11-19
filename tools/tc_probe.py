import urllib.request, re
UA={'User-Agent':'Mozilla/5.0'}
def get(u):
    try: return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60).read().decode('utf-8','replace')
    except Exception as e: return 'ERR '+str(e)
for Y,b in (('2027','sh'),('2026','io')):
    h=get('https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/%s/'%Y)
    for f in sorted(set(re.findall(r'href="(b%s\d\d%s\.dat)"'%(b,Y),h))):
        t=get('https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/%s/%s'%(Y,f)).strip().splitlines()
        if t and '2026111' in t[-1]: print(f, t[-1][:100])
