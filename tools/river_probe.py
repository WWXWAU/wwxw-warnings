"""Probe 34: the shire road report API (/api/roadreports/getReportItems) and which WA councils have it."""
import sys, re, json, urllib.request
BUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36', 'Accept': 'application/json, text/javascript, */*; q=0.01', 'X-Requested-With': 'XMLHttpRequest'}
def get(u, data=None):
    r = urllib.request.Request(u, headers=BUA, data=data)
    return urllib.request.urlopen(r, timeout=40).read().decode('utf-8', 'replace')
t = get('https://www.swek.wa.gov.au/roadreport/')
for m in re.finditer(r'getReportItems', t): print('JS:', re.sub(r'\s+', ' ', t[m.start() - 700:m.start() + 900])); break
for host in ('www.swek.wa.gov.au', 'eastpilbara.wa.gov.au'):
    for u in ('https://%s/api/roadreports/getReportItems?displayType=map' % host, 'https://%s/api/roadreports/getReportItems?displayType=table' % host):
        try:
            x = get(u); print('\n##', u, len(x)); print(x[:2500])
        except Exception as e: print('\n##', u, 'ERR', e)
HOSTS = ['www.sdwk.wa.gov.au', 'www.ashburton.wa.gov.au', 'www.hallscreek.wa.gov.au', 'www.broome.wa.gov.au', 'www.karratha.wa.gov.au', 'www.porthedland.wa.gov.au',
         'www.carnarvon.wa.gov.au', 'www.uppergascoyne.wa.gov.au', 'www.exmouth.wa.gov.au', 'www.sharkbay.wa.gov.au', 'www.meekashire.wa.gov.au', 'www.wiluna.wa.gov.au',
         'www.ngaanyatjarraku.wa.gov.au', 'www.cue.wa.gov.au', 'www.sandstone.wa.gov.au', 'www.mtmagnet.wa.gov.au', 'www.yalgoo.wa.gov.au', 'www.murchison.wa.gov.au',
         'www.laverton.wa.gov.au', 'www.leonora.wa.gov.au', 'www.menzies.wa.gov.au', 'www.coolgardie.wa.gov.au', 'www.dundas.wa.gov.au', 'www.ravensthorpe.wa.gov.au',
         'www.esperance.wa.gov.au', 'www.jerramungup.wa.gov.au', 'www.northampton.wa.gov.au', 'www.chapmanvalley.wa.gov.au', 'www.mullewa.wa.gov.au', 'www.cgg.wa.gov.au',
         'www.morawa.wa.gov.au', 'www.mingenew.wa.gov.au', 'www.threesprings.wa.gov.au', 'www.carnamah.wa.gov.au', 'www.perenjori.wa.gov.au', 'www.dalwallinu.wa.gov.au',
         'www.kalgoorlieboulder.wa.gov.au', 'www.ckb.wa.gov.au', 'www.halls-creek.wa.gov.au', 'www.wyndham.wa.gov.au']
print('\n== API on other councils')
for h in HOSTS:
    try:
        x = get('https://%s/api/roadreports/getReportItems?displayType=map' % h)
        ok = x.strip()[:1] in '[{'
        print(h, 'OK' if ok else 'not json', len(x), x[:200].replace('\n', ' ') if ok else '')
    except Exception as e: print(h, 'ERR', str(e)[:60])
