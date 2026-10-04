"""Short real-HTTP comparisons for non-table renderers, also usable from ptop."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path
import time

import httpx

from .browser_profile import run


KINDS = ('json', 'markdown', 'html', 'text', 'code', 'image', 'traceback')


def payload(kind, revision):
    marker = f'revision{revision}'
    if kind == 'json':
        return {'revision': marker, 'items': [
            {'id': i, 'name': f'name_{i}', 'values': list(range(10))} for i in range(400)]}
    if kind == 'markdown':
        return f'# {marker}\n\n' + '\n'.join(
            f'## Section {i}\n\nSome **bold** text and a [link](https://example.com).\n\n- a\n- b\n'
            for i in range(150))
    if kind == 'html':
        return f'<h1>{marker}</h1>' + '<p>Hello &amp; goodbye café</p>' * 1000
    if kind == 'text':
        return marker + '\n' + 'Log line with <>& and café\n' * 1000
    if kind == 'code':
        return f'# {marker}\n' + 'print("hello")\n' * 1000
    if kind == 'image':
        return {'mime': 'image/png', 'filename': marker + '.png',
                'data_b64': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8ioAAAAASUVORK5CYII='}
    return {'type': 'traceback', 'exc_type': 'ValueError', 'exc_msg': marker, 'frames': [
        {'filename': f'/tmp/file_{i}.py', 'lineno': i + 1, 'function': 'run',
         'line': 'raise ValueError("failed")'} for i in range(30)]}


async def exercise(args, base_url, monitor, server, records, streams):
    metrics = {}
    phase = 'setup'

    def checkpoint():
        start = len(monitor.samples)
        monitor.sample()
        for row in monitor.samples[start:]:
            row['phase'] = phase
        if monitor.watchdog_triggered or server.poll() is not None:
            raise RuntimeError('receiver exited or exceeded RSS watchdog')
        sample = next(s for s in reversed(monitor.samples) if s['role'] == 'server')
        return {'cpu_s': sample['cpu_user_s'] + sample['cpu_system_s'],
                'rss_bytes': sample['rss_bytes'], 'uss_bytes': sample['uss_bytes'],
                'wall_s': time.monotonic()}

    async with httpx.AsyncClient(base_url=base_url, timeout=args.timeout, trust_env=False,
                                 limits=httpx.Limits(max_connections=args.clients + 4)) as client:
        async def request(route, *, kind, revision, publishing=False):
            started = time.monotonic()
            row = {'phase': phase, 'route': route, 'started_s': started,
                   'status_code': None, 'response_bytes': 0, 'error': None}
            try:
                if publishing:
                    response = await client.post('/publish', json={
                        'view_id': f'bench:{kind}', 'kind': 'artifact', 'force': True,
                        'artifact_kind': kind, 'artifact': payload(kind, revision),
                    })
                else:
                    response = await client.get(f'/{route}?view=bench:{kind}')
                row.update(duration_s=time.monotonic() - started, status_code=response.status_code,
                           response_bytes=len(response.content))
                response.raise_for_status()
                if publishing and response.json().get('ignored'):
                    raise ValueError('publication ignored')
                if route == 'artifact':
                    if f'revision{revision}' not in response.json()['html']:
                        raise ValueError('missing current revision')
                    row['sha256'] = hashlib.sha256(response.content).hexdigest()
            except Exception as exc:
                row['error'] = f'{type(exc).__name__}: {exc}'
            row.setdefault('duration_s', time.monotonic() - started)
            records.append(row)
            if row['error']:
                raise RuntimeError(row['error'])

        for kind in args.kinds:
            for revision in range(1, args.cycles + 1):
                phase = f'{kind}.publish'
                await request('publish', kind=kind, revision=revision, publishing=True)
                for name, waves in (('cold', 1), ('warm', args.rounds)):
                    phase = f'{kind}.{name}'
                    before = checkpoint()
                    for _ in range(waves):
                        requests = [request('artifact', kind=kind, revision=revision)
                                    for _ in range(args.clients)]
                        if name == 'cold':
                            requests.append(request('status', kind=kind, revision=revision))
                        await asyncio.gather(*requests)
                    after = checkpoint()
                    metrics.setdefault(phase, []).append({
                        **after, 'cpu_s': after['cpu_s'] - before['cpu_s'],
                        'wall_s': after['wall_s'] - before['wall_s'],
                    })
        phase = 'settling'
        await asyncio.sleep(args.settle)
        metrics[phase] = [checkpoint()]
    return records, streams, metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--kinds', nargs='+', choices=KINDS, default=list(KINDS))
    parser.add_argument('--clients', type=int, default=6)
    parser.add_argument('--cycles', type=int, default=3)
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--settle', type=float, default=1)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--max-seconds', type=float, default=180)
    parser.add_argument('--max-server-rss-mb', type=int, default=512)
    args = parser.parse_args(argv)
    if not (1 <= args.clients <= 64 and 1 <= args.cycles <= 20 and 1 <= args.rounds <= 100
            and 0 <= args.settle < args.max_seconds <= 1800 and args.timeout > 0
            and args.max_server_rss_mb > 0):
        parser.error('invalid workload or safety budget')
    args.sse_lifetime = 600
    args.cheap_p95_ms = 0
    return run(args, exercise_fn=exercise, case_id='server.artifact.concurrent',
               cpu_route='artifact', harness_paths=(__file__,),
               config_overrides={'security-settings': {'tracebacks_enabled': True}})


if __name__ == '__main__':
    raise SystemExit(main())
