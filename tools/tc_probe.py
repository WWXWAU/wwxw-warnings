import urllib.request, re
UA={'User-Agent':'Mozilla/5.0'}
def get(u):
    try: return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60).read().decode('utf-8','replace')
    except Exception as e: return 'ERR '+str(e)
for Y in ('2026','2027'):
    for kind in ('bdecks_open','adecks_open'):
        u='https://hurricanes.ral.ucar.edu/repository/data/%s/%s/'%(kind,Y); h=get(u)
        rows=re.findall(r'href="([ab](?:sh|io|wp)\d{6}\.dat)".{0,120}?(\d{4}-\d\d-\d\d \d\d:\d\d|\d\d-[A-Za-z]{3}-\d{4} \d\d:\d\d)',h,re.S)
        print(kind,Y,h[:60] if h.startswith('ERR') else '', [r for r in rows if r[1] >= '2026-11' or 'Nov-2026' in r[1]][:40])
for Y in ('2026','2027'):
    h=get('https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/%s/'%Y)
    for f in sorted(set(re.findall(r'href="(b(?:sh|io)9\d%s\.dat)"'%Y,h)))[-6:]:
        t=get('https://hurricanes.ral.ucar.edu/repository/data/bdecks_open/%s/%s'%(Y,f)).strip().splitlines()
        print(f, t[-1][:120] if t else '')
