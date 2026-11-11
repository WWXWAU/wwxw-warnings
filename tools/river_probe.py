"""Probe 29: which stations in the cyclone page's coastal obs feed look like the removed shared sites."""
import sys, json, collections
sys.path.insert(0, 'rivers'); import rivers as RV
t = RV.get('https://script.google.com/macros/s/AKfycbyoxJApPxqA86gVVXen0USujHH7OAz3_nEwonfV-8j1G4pWAyKU7aIBRCRxsYZ5DcdJ/exec?page=cyclobs', 150, 2)
d = json.loads(t)
print('keys', list(d.keys()), 'stations', len(d['st']), collections.Counter(s.get('s') for s in d['st']))
print('example', d['st'][0])
odd = [s for s in d['st'] if 'station' in s.get('n', '').lower() or ' of ' in s.get('n', '') or s.get('s') not in ('BOM', 'DPIRD', 'DWER')]
print('odd', len(odd))
for s in odd[:40]: print({k: s[k] for k in s if k not in ('now', 'h', 'hist')})
