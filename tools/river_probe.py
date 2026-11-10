"""Probe 16: subcatchment paging."""
import json, sys, urllib.parse
sys.path.insert(0, 'rivers'); import rivers as RV
for w, o in [('OBJECTID > 0', 'OBJECTID'), ('objectid > 0', 'objectid'), ('1=1', '')]:
    q = RV.SUBCATCH + '?' + urllib.parse.urlencode({'where': w, 'outFields': 'objectid,ufi', 'returnGeometry': 'false', 'orderByFields': o, 'resultRecordCount': 3, 'f': 'json'})
    print(w, RV.get(q, 60, 1)[:400])
