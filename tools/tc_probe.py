import urllib.request, re, collections, time
UA={'User-Agent':'Mozilla/5.0 (WWXW verification)'}
def get(u):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60); return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, b''
    except Exception as e: return str(e)[:60], b''
R='https://hurricanes.ral.ucar.edu/repository/data/adecks_open/'
for y in ('2024','2025','2026'):
    c,b=get(R+y+'/'); names=sorted(set(re.findall(rb'ash\d{6}\.dat(?:\.gz)?',b)))
    print('UCAR',y,c,len(names),[n.decode() for n in names[:40]])
c,b=get(R+'2025/ash222025.dat'); print('sample',c,len(b))
if b:
    t=collections.Counter(l.split(b',')[4].strip() for l in b.splitlines() if l.count(b',')>8)
    print(t.most_common(80))
# Weather Lab: what comes back for one week, 6-hourly
G='https://deepmind.google.com/science/weatherlab/download/cyclones/{m}/ensemble_mean/paired/atcf/{m}_{d}_atcf_a_deck.txt'
import datetime as dt
for m in ('FNV3','GENC'):
    cnt=collections.Counter(); d=dt.datetime(2025,2,1)
    while d<dt.datetime(2025,2,8):
        c,b=get(G.format(m=m,d=d.strftime('%Y_%m_%dT%H_00'))); cnt[c]+=1
        if c==200 and d.hour==0 and d.day==3:
            L=[l for l in b.decode().splitlines() if not l.startswith('#')]
            print(m,'lines',len(L),'storms',sorted(set(l.split(',')[0]+l.split(',')[1] for l in L if l.count(',')>8)),'taus',sorted(set(int(l.split(',')[5]) for l in L if l.count(',')>8))[:60])
            print('\n'.join(L[:3]))
        d+=dt.timedelta(hours=6); time.sleep(0.3)
    print(m,dict(cnt))
for alt in ('ensemble/paired/atcf','ensemble_mean/atcf','ensemble_mean/unpaired/atcf'):
    u='https://deepmind.google.com/science/weatherlab/download/cyclones/FNV3/'+alt+'/FNV3_2025_02_03T00_00_atcf_a_deck.txt'
    c,b=get(u); print(alt,c,len(b))
