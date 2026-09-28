"""Private history policy must cover content URLs, not just discovery."""
import pytest
from fastapi.testclient import TestClient

from plotsrv import config, store
from plotsrv.app import app
from plotsrv.storage.backend import write_snapshot


def test_dashboard_only_refreshes_catalogue_when_views_route_is_readable(monkeypatch):
    monkeypatch.setattr(config, "get_views_local_only", lambda: True)
    remote = TestClient(app, client=("198.51.100.1", 1000))
    local = TestClient(app, client=("127.0.0.1", 1000))
    forwarded = TestClient(app, client=("127.0.0.1", 1000), headers={"X-Forwarded-For": "198.51.100.1"})

    for client, allowed in ((remote, False), (local, True), (forwarded, False)):
        response = client.get("/")
        assert response.status_code == 200
        assert f'"view_menu_refresh_allowed": {str(allowed).lower()}' in response.text
        assert client.get("/views").status_code == (200 if allowed else 403)

    monkeypatch.setattr(config, "get_views_local_only", lambda: False)
    assert '"view_menu_refresh_allowed": true' in remote.get("/").text


@pytest.mark.parametrize("endpoint", ["/plot", "/artifact", "/table/data", "/table/export"])
def test_snapshot_policy_precedes_payload_loading(monkeypatch, endpoint):
    monkeypatch.setattr(config, "get_history_local_only", lambda: True)
    remote = TestClient(app, client=("198.51.100.1", 1000))
    assert remote.get(endpoint, params={"view": "missing", "snapshot": "unknown"}).status_code == 403
    # Ordinary live views keep their existing read policy.
    assert remote.get(endpoint, params={"view": "missing"}).status_code != 403


@pytest.mark.parametrize("endpoint,setting", [
    ("/stream/history", "get_history_local_only"),
    ("/stream/status", "get_status_local_only"),
])
def test_stream_routes_obey_read_policy(monkeypatch, endpoint, setting):
    monkeypatch.setattr(config, setting, lambda: True)
    assert TestClient(app, client=("198.51.100.1", 1000)).get(endpoint, params={"view": "missing"}).status_code == 403
    assert TestClient(app, client=("127.0.0.1", 1000)).get(endpoint, params={"view": "missing"}).status_code == 404
    assert TestClient(app, client=("127.0.0.1", 1000), headers={"X-Forwarded-For": "198.51.100.1"}).get(endpoint, params={"view": "missing"}).status_code == 403


def test_snapshot_read_local_and_explicit_public_modes(tmp_path, monkeypatch):
    store.reset()
    monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
    snap = write_snapshot(root_dir=tmp_path, view_id="report", kind="text", obj="retained report")
    params = {"view": "report", "snapshot": snap.snapshot_id}
    monkeypatch.setattr(config, "get_history_local_only", lambda: True)
    assert TestClient(app, client=("127.0.0.1", 1000)).get("/artifact", params=params).status_code == 200
    monkeypatch.setattr(config, "get_history_local_only", lambda: False)
    result = TestClient(app, client=("198.51.100.1", 1000)).get("/artifact", params=params)
    assert result.status_code == 200
    assert "retained report" in result.json()["html"]


@pytest.mark.parametrize("endpoint,method", [("/stream/data", "data"), ("/stream/summary", "summary")])
def test_restored_history_is_private_even_through_live_urls(monkeypatch, endpoint, method):
    from plotsrv.http_streams import stream_registry

    monkeypatch.setattr(config, "get_history_local_only", lambda: True)
    monkeypatch.setattr(stream_registry, method, lambda **kwargs: {"historical": True, "records": ["old data"]})
    remote = TestClient(app, client=("198.51.100.1", 1000))
    assert remote.get(endpoint, params={"view": "restored"}).status_code == 403
