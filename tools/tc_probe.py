import urllib.request
UA={'User-Agent':'Mozilla/5.0'}
for u in ['https://www.metoc.navy.mil/jtwc/products/abioweb.txt','https://www.metoc.navy.mil/jtwc/products/abpwweb.txt']:
    try: t=urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60).read().decode('utf-8','replace')
    except Exception as e: t='ERR '+str(e)
    print('=====',u); print(t[:6000])
