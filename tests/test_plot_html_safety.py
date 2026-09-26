from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from plotsrv import config
from plotsrv.app import app
from plotsrv.renderers.plot import PlotRenderer
from plotsrv.storage.backend import write_snapshot


class Images(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.images = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images.append(dict(attrs))


@pytest.mark.parametrize("historical", [False, True])
def test_plot_identifiers_cannot_inject_attributes_or_query_parameters(tmp_path, monkeypatch, historical):
    vid = 'report" onerror="window.compromised=1" data-x="&snapshot=other café'
    expected = {"view": [vid]}
    if historical:
        monkeypatch.setattr(config, "get_storage_root_dir", lambda: tmp_path)
        snap = write_snapshot(root_dir=tmp_path, view_id=vid, kind="plot", obj=b"fixture")
        response = TestClient(app, client=("127.0.0.1", 1)).get(
            "/artifact", params={"view": vid, "snapshot": snap.snapshot_id},
        )
        assert response.status_code == 200
        markup = response.json()["html"]
        expected["snapshot"] = [snap.snapshot_id]
    else:
        markup = PlotRenderer().render(b"fixture", view_id=vid).html
    images = Images(markup).images
    assert len(images) == 1
    assert set(images[0]) == {"id", "src", "alt"}
    assert parse_qs(urlsplit(images[0]["src"]).query) == expected
