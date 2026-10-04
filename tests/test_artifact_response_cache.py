from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from plotsrv import render_cache, store
from plotsrv.app import app, get_artifact
from plotsrv.http_security import require_snapshot_read


@pytest.fixture(autouse=True)
def clean():
    store.reset()
    yield
    store.reset()
    app.dependency_overrides.clear()


@pytest.mark.parametrize('kind,obj', [
    ('json', {'items': [1, None, 'café', '<script>'], 'nested': {'ok': True}}),
    ('markdown', '# Hello\n\n**café** <script>alert(1)</script>'),
    ('html', '<h1>Hello</h1><script>alert(1)</script>'),
    ('text', 'hello\n<>& café'),
    ('python', 'print("café")'),
    ('code', 'SELECT * FROM results;'),
    ('image', {'mime': 'image/png', 'data_b64': 'YWJj', 'filename': 'café.png'}),
    ('traceback', {'type': 'traceback', 'exc_type': 'ValueError', 'exc_msg': 'bad', 'frames': []}),
    ('watch_error', 'Missing file'),
    ('publish_error', 'Rejected publication'),
])
def test_http_bytes_match_original_route_and_skip_repeat_rendering(kind, obj, monkeypatch):
    module = importlib.import_module('plotsrv.app')
    reference = FastAPI()
    reference.get('/artifact')(get_artifact)
    store.set_artifact(kind=kind, obj=obj, view_id='test')
    with TestClient(reference) as old:
        expected = old.get('/artifact?view=test')
    render_cache.clear_rendered_artifact_cache()
    original = module._render_artifact_response
    calls = []
    def tracked(**kwargs):
        calls.append(1)
        return original(**kwargs)
    monkeypatch.setattr(module, '_render_artifact_response', tracked)
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        for _ in range(2):
            response = client.get('/artifact?view=test')
            assert response.status_code == expected.status_code == 200
            assert response.json()['kind'] == kind
            assert response.content == expected.content
            assert response.headers['content-type'] == expected.headers['content-type']
            assert response.headers['content-length'] == expected.headers['content-length']
    assert calls == [1]
    assert all(isinstance(entry.response, bytes) for entry in render_cache._CACHE._entries.values())


def test_hits_still_require_access_and_preserve_python_call_contract():
    store.set_artifact(kind='text', obj='hello', view_id='test')
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        expected = client.get('/artifact?view=test').json()
        assert get_artifact(view='test') == expected
        assert client.get('/artifact?view=test').json() == expected
        def reject():
            raise HTTPException(403, 'denied')
        app.dependency_overrides[require_snapshot_read] = reject
        assert client.get('/artifact?view=test').status_code == 403


def test_concurrent_http_readers_share_one_render_and_encoding(monkeypatch):
    module = importlib.import_module('plotsrv.app')
    original = module._render_artifact_response
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked(**kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(module, '_render_artifact_response', blocked)
    store.set_artifact(kind='markdown', obj='# Hello', view_id='test')
    with TestClient(app, client=('127.0.0.1', 50000)) as client, ThreadPoolExecutor(max_workers=20) as pool:
        pending = [pool.submit(client.get, '/artifact?view=test') for _ in range(20)]
        try:
            assert entered.wait(5)
            deadline = time.monotonic() + 5
            while render_cache._HTTP_BUILDS.stats()['waiters'] < 20 and time.monotonic() < deadline:
                time.sleep(.001)
            assert render_cache._HTTP_BUILDS.stats()['waiters'] == 20
        finally:
            release.set()
        responses = [future.result(5) for future in pending]
    assert calls == [1]
    assert all(r.status_code == 200 and r.content == responses[0].content for r in responses)
    assert render_cache._HTTP_BUILDS.stats() == dict(entries=0, bytes=0, builds=0, waiters=0)


@pytest.mark.parametrize('replacement', ['republish', 'reset', 'plot'])
@pytest.mark.parametrize('direct', [False, True])
def test_old_build_cannot_replace_new_cached_revision(monkeypatch, replacement, direct):
    module = importlib.import_module('plotsrv.app')
    original = module._render_artifact_response
    entered, release = threading.Event(), threading.Event()
    def blocked(**kwargs):
        if kwargs['obj'] == 'old':
            entered.set()
            assert release.wait(5)
        return original(**kwargs)
    monkeypatch.setattr(module, '_render_artifact_response', blocked)
    store.set_artifact(kind='text', obj='old', view_id='test')
    with TestClient(app, client=('127.0.0.1', 50000)) as client, ThreadPoolExecutor() as pool:
        pending = (pool.submit(get_artifact, view='test') if direct
                   else pool.submit(client.get, '/artifact?view=test'))
        try:
            assert entered.wait(5)
            if replacement == 'reset':
                store.reset()
            elif replacement == 'plot':
                store.set_plot(b'png', view_id='test')
            else:
                store.set_artifact(kind='text', obj='new', view_id='test')
                assert 'new' in client.get('/artifact?view=test').json()['html']
        finally:
            release.set()
        result = pending.result(5)
        assert 'old' in (result if direct else result.json())['html']
    entries = render_cache._CACHE._entries
    if replacement == 'republish':
        assert len(entries) == 1
        assert b'new' in next(iter(entries.values())).response
    else:
        assert not entries


def test_remote_status_bypasses_encoded_hit(monkeypatch):
    from plotsrv import remote_watch
    store.set_artifact(kind='text', obj='hello', view_id='test')
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        client.get('/artifact?view=test')
        monkeypatch.setattr(remote_watch, 'public_meta', lambda vid: {
            'status': 'disconnected', 'message': 'Publisher disconnected', 'limitation': 'preview',
        })
        result = client.get('/artifact?view=test').json()
        assert result['meta']['status'] == 'disconnected'
        assert 'Publisher disconnected' in result['html']


def test_failed_encoding_is_retried_and_not_cached(monkeypatch):
    module = importlib.import_module('plotsrv.app')
    original = module._render_artifact_response
    store.set_artifact(kind='text', obj='hello', view_id='test')
    monkeypatch.setattr(module, '_render_artifact_response', lambda **kw: {'html': object()})
    with TestClient(app, client=('127.0.0.1', 50000), raise_server_exceptions=False) as client:
        assert client.get('/artifact?view=test').status_code == 500
        assert not render_cache._CACHE._entries
        assert render_cache._HTTP_BUILDS.stats()['builds'] == 0
        monkeypatch.setattr(module, '_render_artifact_response', original)
        assert client.get('/artifact?view=test').status_code == 200


def test_encoded_and_dictionary_entries_share_budget_and_evict_oldest():
    cache = render_cache._RenderedArtifactCache(max_entries=2, max_bytes=1000, max_entry_bytes=800)
    cache.put(view_id='a', revision=1, response={'html': 'a'})
    cache.put_bytes(view_id='b', revision=2, body=b'b' * 500)
    cache.put_bytes(view_id='c', revision=3, body=b'c' * 500)
    assert cache._total_bytes <= 1000
    assert cache.get(view_id='a', revision=1) is None
    assert cache.get_bytes(view_id='b', revision=2) is None
    assert cache.get_bytes(view_id='c', revision=3) == b'c' * 500
    cache.put_bytes(view_id='d', revision=4, body=b'd' * 900)
    assert cache.get_bytes(view_id='d', revision=4) is None
    cache.invalidate('c')
    assert cache._total_bytes == 0
