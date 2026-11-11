"""Probe 40: draw example alert story images with the live satellite picture (handed over on the review branch)."""
import subprocess, sys, json, os, datetime as dt
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--user', 'pillow', 'numpy', 'h5py'], check=True)
import site, importlib; sys.path.insert(0, site.getusersitepackages()); importlib.invalidate_caches()
sys.path.insert(0, '.')
import alertimg
os.makedirs('review', exist_ok=True)
now = dt.datetime.now(dt.timezone.utc).isoformat()
alertimg.render({'id': 'ex-rain', 'kind': 'rain', 'title': 'Heavy rainfall', 'time': now, 'items': [
    {'name': 'Dimond Gorge', 'district': 'Kimberley', 'src': 'DWER', 'lat': -17.03, 'lng': 126.30, 'vals': [{'v': 30.2, 'unit': 'mm', 'label': '1 hr'}]}]},
    'review/ex-rain-story.png', 'review/ex-rain-post.png')
alertimg.render({'id': 'ex-rain2', 'kind': 'rain', 'title': 'Heavy rainfall', 'time': now, 'items': [
    {'name': 'Mount Magnet', 'district': 'Central West', 'src': 'BOM', 'lat': -28.06, 'lng': 117.84, 'vals': [{'v': 31.4, 'unit': 'mm', 'label': '1 hr'}, {'v': 62.0, 'unit': 'mm', 'label': '3 hrs'}]},
    {'name': 'Yalgoo', 'district': 'Central West', 'src': 'DPIRD', 'lat': -28.34, 'lng': 116.68, 'vals': [{'v': 26.2, 'unit': 'mm', 'label': '1 hr'}]}]},
    'review/ex-rain2-story.png', None)
alertimg.render({'id': 'ex-gust', 'kind': 'gust', 'title': 'Damaging wind gusts', 'time': now, 'items': [
    {'name': 'Iron Bridge Mine', 'district': 'Pilbara', 'src': 'BOM', 'lat': -21.3, 'lng': 118.9, 'vals': [{'v': 96, 'unit': 'km/h', 'label': 'gust'}]}]},
    'review/ex-gust-story.png', None)
print(os.listdir('review'))
