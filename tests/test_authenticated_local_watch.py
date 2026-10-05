"""Public start_server watches use this receiver's credential and exact view ID."""
import os
from pathlib import Path
import socket
import subprocess
import sys

import yaml


def test_authenticated_local_watch_updates_exact_locked_id(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    source = tmp_path / 'orders.log'
    source.write_text('2026-06-30T08:00:00Z INFO initial\n')
    config = tmp_path / 'plotsrv.yml'
    config.write_text(yaml.safe_dump({
        'server-settings': {
            'ingestion': {'bearer_token_env': 'LOCAL_WATCH_TEST_TOKEN'},
            'admission': {'mode': 'catalogue-locked', 'allowed_ids': ['exact:operations-log']},
        },
        # Local receiver watches must not inherit this separate destination.
        'publisher-settings': {'destination': {'url': 'http://127.0.0.1:1',
                                              'bearer_token_env': 'OUTBOUND_TEST_TOKEN'}},
        'storage-settings': {'enabled': False},
    }))
    script = '''
import json, sys, time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
import plotsrv as ps
config, source, port = sys.argv[1:]
source = Path(source)
opener = build_opener(ProxyHandler({}))
def rendered():
    with opener.open(f'http://127.0.0.1:{port}/artifact?view=exact:operations-log', timeout=2) as response:
        return json.load(response)['html']
try:
    ps.start_server(config=config, port=int(port), auto_on_show=False,
        watches=[ps.WatchConfig(path=source, view_id='exact:operations-log',
            label='Readable label', section='Different section', kind='text', materialization='memory')])
    for expected in ('initial', 'changed'):
        if expected == 'changed': source.write_text('2026-06-30T08:01:00Z WARN changed\\n')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if expected in rendered(): break
            except OSError: pass
            time.sleep(.1)
        else: raise AssertionError('Local watch did not deliver ' + expected)
finally:
    ps.stop_server(join=True)
'''
    result = subprocess.run([sys.executable, '-c', script, str(config), str(source), str(port)],
                            env={**os.environ, 'LOCAL_WATCH_TEST_TOKEN': 'local-fixture',
                                 'OUTBOUND_TEST_TOKEN': 'outbound-fixture'},
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
