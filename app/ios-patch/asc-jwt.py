# A short-lived App Store Connect API token (ES256 JWT) from the .p8 key: python3 asc-jwt.py key.p8 KEY_ID ISSUER_ID
import base64, json, subprocess, sys, time

def b64(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

key, kid, iss = sys.argv[1:4]
head = b64(json.dumps({'alg': 'ES256', 'kid': kid, 'typ': 'JWT'}).encode())
body = b64(json.dumps({'iss': iss, 'iat': int(time.time()), 'exp': int(time.time()) + 900, 'aud': 'appstoreconnect-v1'}).encode())
msg = (head + '.' + body).encode()
der = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', key], input=msg, capture_output=True, check=True).stdout
# DER signature -> raw r||s (64 bytes)
i = 3 + (der[1] > 0x80)
rl = der[i]; r = der[i + 1:i + 1 + rl]; j = i + 1 + rl + 1; sl = der[j]; s = der[j + 1:j + 1 + sl]
sig = r.lstrip(b'\0').rjust(32, b'\0') + s.lstrip(b'\0').rjust(32, b'\0')
print(head + '.' + body + '.' + b64(sig))
