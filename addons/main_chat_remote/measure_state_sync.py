"""Compare identical snapshots; output sizes only, never conversation content."""
import argparse
import base64
import importlib.util
import json
from pathlib import Path
import threading
import time
from http.server import ThreadingHTTPServer
import urllib.request
import urllib.parse
from .state_sync import StateSyncStore, encoded


def wire_bytes(payload, transport):
    raw = encoded(payload)
    if transport == 'http': return len(raw)
    if transport == 'websocket': return len(raw) + (2 if len(raw) < 126 else 4 if len(raw) < 65536 else 10)
    header = dict(v=1, id='measure', status=200, contentType='application/json')
    if len(raw) < 45000:
        return len(encoded(dict(header, type='response', body=payload)))
    result = len(encoded(dict(header, type='file-start', bytes=len(raw))))
    for n in range(0, len(raw), 24576):
        result += len(encoded(dict(v=1, id='measure', type='file-chunk', data=base64.b64encode(raw[n:n+24576]).decode())))
    return result + len(encoded(dict(v=1, id='measure', type='file-end')))


def measure_snapshots(states, transport):
    store, cursor, before, after = StateSyncStore(), {}, [], []
    for state in states:
        original = {'ok':True, 'state':state}
        optimized = store.respond('measurement', state, **cursor)
        e = optimized['state_sync']; cursor = {k:e[k] for k in ('context','epoch','revision')}
        if transport == 'websocket':
            original = {'type':'state','payload':original}
            optimized = {'type':'state_sync','payload':optimized}
        before.append(wire_bytes(original, transport)); after.append(wire_bytes(optimized, transport))
    return dict(samples=len(before), before_initial=before[0], after_initial=after[0],
                before_steady=sum(before[1:]), after_steady=sum(after[1:]),
                before_total=sum(before), after_total=sum(after))


def loopback_measure(bridge_info, baseline_path, samples, interval):
    """Actual HTTP response bodies read from old/new backends on isolated ports.

    Both receive the same fresh snapshot, held only in memory. Production service
    is never replaced/restarted; no commands are issued to the desktop.
    """
    from .remote_backend import MainChatRemoteBackend
    info = json.loads(Path(bridge_info).read_text(encoding='utf-8'))
    url = urllib.parse.urlsplit(info['url'])
    if url.hostname not in ('127.0.0.1', 'localhost', '::1') or url.scheme != 'http':
        raise ValueError('Measurement source must be the local desktop bridge')
    spec = importlib.util.spec_from_file_location('addons.main_chat_remote._bandwidth_baseline', baseline_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    current = [{}]
    services, threads = [], []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    totals = {'before':[], 'after':[]}; cursor = {}
    try:
        for backend_type in (module.MainChatRemoteBackend, MainChatRemoteBackend):
            backend = backend_type(host='127.0.0.1', pairing_code='987654')
            backend.bridge.json_request = lambda *args: current[0]
            backend.bridge.request = lambda *args: (200, json.dumps(current[0],ensure_ascii=False).encode(), 'application/json')
            handler = backend._handler_class()
            handler.log_message = lambda *args: None
            server = ThreadingHTTPServer(('127.0.0.1',0), handler)
            thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            services.append((server,backend)); threads.append(thread)
        start = time.monotonic()
        for n in range(samples):
            if n: time.sleep(max(0, start + n*interval - time.monotonic()))
            request = urllib.request.Request(info['url'].rstrip('/')+'/api/state', headers={'X-NC-Bridge-Token':info['token']})
            with opener.open(request,timeout=5) as reply: current[0] = json.load(reply)
            if current[0].get('ok') is not True: raise ValueError('Fresh source unavailable')
            for index, name in enumerate(('before','after')):
                suffix = '?' + urllib.parse.urlencode({'sync':1,**cursor}) if index else ''
                request = urllib.request.Request(f'http://127.0.0.1:{services[index][0].server_port}/api/state{suffix}',headers={'X-NC-Phone-Code':'987654'})
                with opener.open(request, timeout=5) as reply: raw = reply.read()
                totals[name].append(len(raw))
                if index:
                    e = json.loads(raw)['state_sync']; cursor = {k:e[k] for k in ('context','epoch','revision')}
        return {'measurement':'actual loopback HTTP response-body bytes, identical fresh desktop snapshots',
                'samples':samples, 'elapsed_seconds':round(time.monotonic()-start,2),
                'excluded':'HTTP/TCP/IP overhead, media RTP, TURN, Internet routing; not a carrier measurement',
                **{name:{'initial':counts[0],'steady':sum(counts[1:]),'total':sum(counts)} for name,counts in totals.items()}}
    finally:
        for server, backend in services:
            server.shutdown(); server.server_close(); backend.local_av.close()
        for thread in threads: thread.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-info'); parser.add_argument('--baseline-backend')
    parser.add_argument('--samples',type=int,default=60)
    args = parser.parse_args()
    if not 2 <= args.samples <= 120: parser.error('samples must be 2–120')
    if args.bridge_info:
        if not args.baseline_backend: parser.error('baseline-backend is required with bridge-info')
        print(json.dumps(loopback_measure(args.bridge_info,args.baseline_backend,args.samples,1),indent=2))
        return
    states = [{'visual':{'settings':{'large':'x'*36000},'state':{'mood':'neutral' if n<30 else 'happy'}},
               'chat':{'messages':[] if n<20 else [{'text':'synthetic measurement'}]},'tick':n} for n in range(args.samples)]
    print(json.dumps({'measurement':'synthetic serialization/framing comparison, not network capture',
                      **{kind:measure_snapshots(states,kind) for kind in ('http','websocket','peer')}},indent=2))


if __name__ == '__main__': main()
