import urllib.request, json, time

payload = json.dumps({'question': 'what demand was not met for item 2000-293-667', 'history': []}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8010/api/chat/stream',
    data=payload,
    headers={'Content-Type': 'application/json'},
    method='POST'
)
print('Sending request...')
t = time.time()
with urllib.request.urlopen(req, timeout=60) as r:
    buf = b''
    for _ in range(30):
        chunk = r.read(512)
        if not chunk:
            break
        buf += chunk
        lines = buf.split(b'\n')
        for line in lines[:-1]:
            line = line.strip()
            elapsed = time.time() - t
            if line.startswith(b'data: '):
                payload_str = line[6:120].decode('utf-8', errors='replace')
                print(f't={elapsed:.1f}s  {payload_str}')
            elif line.startswith(b': '):
                print(f't={elapsed:.1f}s  [keepalive]')
        buf = lines[-1]
        if time.time() - t > 40:
            print('40s limit reached')
            break
