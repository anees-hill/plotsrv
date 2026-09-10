"""Short source explanations are metadata, never application-code inspection."""

import json
import tracemalloc
from pathlib import Path

import pytest
from plotsrv import descriptions, settings, store, decorators, publisher
from plotsrv.contracts import ViewDescriptor
from plotsrv.ingestion import register_catalogue
from tests.test_snapshot_navigation import client


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "_CTX", settings.RuntimeContext())
    monkeypatch.setattr(settings, "_CONFIG_CACHE", {})
    monkeypatch.delenv("PLOTSRV_CONFIG", raising=False)
    store.reset()
    yield
    store.reset()


@pytest.mark.parametrize(
    "doc",
    [
        " First line.\n   Wrapped line.\n\nSECRET details",
        "\n First line.\n Wrapped line.\n  \nSECRET details",
        "\r\n First line.\r\n Wrapped line.\r\n\r\nSECRET details",
        "First line.\n Wrapped line.\n\u2003\nSECRET details",
    ],
)
def test_bounded_first_paragraph_and_opt_out(doc):
    assert (
        descriptions.source_description("a", docstring=doc, policy={})
        == "First line. Wrapped line."
    )
    assert (
        descriptions.source_description(
            "a", docstring=doc, policy={"extract_docstrings": False}
        )
        is None
    )
    policy = {"extract_docstrings": True, "views": {"a": {"extract_docstrings": False}}}
    assert descriptions.source_description("a", docstring=doc, policy=policy) is None
    policy["views"]["a"]["description"] = "Explicit"
    assert (
        descriptions.source_description("a", "Publisher", docstring=doc, policy=policy)
        == "Explicit"
    )
    policy["views"]["a"]["description"] = ""
    assert (
        descriptions.source_description("a", "Publisher", docstring=doc, policy=policy)
        == ""
    )


def test_huge_docstring_allocations_are_independent_of_full_length():
    doc = "Summary.\n\n" + "SECRET" * 1_000_000
    tracemalloc.start()
    result = descriptions.source_description("a", docstring=doc, policy={})
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result == "Summary."
    assert peak < 100_000
    assert len(descriptions.clean("x" * 1_000_000)) == 512
    print("Description extraction peak bytes:", peak)


def test_no_callable_or_inherited_documentation_hooks():
    class Dangerous:
        def __getattribute__(self, name):
            pytest.fail("Inspected arbitrary object")

    assert descriptions.function_description(Dangerous(), view_id="a") is None

    def dynamic():
        pass

    assert descriptions.function_description(dynamic, view_id="a") is None


def test_unavailable_description_policy_cannot_break_decoration_or_publication(
    monkeypatch,
):
    from plotsrv.publishing.models import PublishTarget

    def unavailable(*a, **kw):
        raise OSError("Description config unavailable")

    monkeypatch.setattr(descriptions, "source_description", unavailable)

    @decorators.view(view_id="a")
    def pipeline():
        """Private if the extraction policy cannot be loaded."""
        return 42

    assert pipeline() == 42
    assert decorators.get_plotsrv_spec(pipeline).description is None
    monkeypatch.setattr(
        publisher, "resolve_publish_target", lambda **kw: PublishTarget("remote")
    )
    monkeypatch.setattr(publisher, "_resolve_async_publish", lambda *a: False)
    monkeypatch.setattr(
        publisher,
        "_post_publish_payload",
        lambda **kw: pytest.fail("Published without metadata policy"),
    )
    publisher.publish_view(42, view_id="a", async_=False)


def test_ast_runtime_fallback_agree_without_imports(tmp_path):
    from plotsrv.discovery import discover_views

    code = 'import plotsrv as ps\nraise RuntimeError("must not import")\n@ps.view(view_id="business")\ndef summary():\n    """Business totals.\n\n    SECRET implementation details.\n    """\n    return 1\n'
    (tmp_path / "source.py").write_text(code)
    found = discover_views(tmp_path)
    assert found[0].description == "Business totals."

    @decorators.view(view_id="business")
    def summary():
        """Business totals.

        SECRET implementation details.
        """
        return 1

    assert decorators.get_plotsrv_spec(summary).description == found[0].description
    (tmp_path / "plotsrv.yml").write_text(
        "description-settings:\n  extract_docstrings: false\n"
    )
    assert discover_views(tmp_path)[0].description is None


@pytest.mark.usefixtures("publisher_payload_transport")
def test_remote_decorator_description_survives_disjoint_receiver(
    client, tmp_path, monkeypatch
):
    @decorators.view(view_id="business", label="Business", port=8999, async_=False)
    def summary():
        """Total fulfilled orders, grouped by region.

        SECRET SQL connection instructions.
        """
        return {"orders": 42}

    captured = []
    monkeypatch.setattr(
        publisher,
        "_post_publish_payload",
        lambda **kw: captured.append(kw["payload"]) or True,
    )
    assert summary() == {"orders": 42}
    assert captured[0]["description"] == "Total fulfilled orders, grouped by region."
    server = tmp_path / "unrelated-server"
    server.mkdir()
    monkeypatch.chdir(server)
    assert client.post("/publish", json=captured[0]).status_code == 200
    assert client.get("/views").json()[0]["description"] == captured[0]["description"]
    assert "SECRET" not in json.dumps(captured)


def test_catalogue_metadata_updates_do_not_touch_content_or_policy(client):
    register_catalogue([ViewDescriptor("a", "A", description="First")], seal=False)
    store.set_artifact(obj="data", kind="text", view_id="a")
    revision = store.get_render_revision(view_id="a")
    menu = store.get_view_menu_revision()
    register_catalogue([ViewDescriptor("a", "A", description="Second")], seal=False)
    assert store.get_view_menu_revision() > menu
    assert store.get_render_revision(view_id="a") == revision
    assert client.get("/views").json()[0]["description"] == "Second"
    menu = store.get_view_menu_revision()
    register_catalogue([ViewDescriptor("a", "A", description="Second")], seal=False)
    assert store.get_view_menu_revision() == menu
    assert (
        client.post(
            "/publish",
            json={
                "view_id": "a",
                "kind": "artifact",
                "artifact_kind": "text",
                "artifact": "new",
            },
        ).status_code
        == 200
    )
    assert client.get("/views").json()[0]["description"] == "Second"
    assert (
        client.post(
            "/publish",
            json={
                "view_id": "a",
                "kind": "artifact",
                "artifact_kind": "text",
                "artifact": "new",
                "description": "",
            },
        ).status_code
        == 200
    )
    assert client.get("/views").json()[0]["description"] == ""


def test_server_config_and_safe_rendering(client, tmp_path):
    text = "<script>window.secret=1</script> & business"
    register_catalogue([ViewDescriptor("a", "A", description="Publisher")], seal=False)
    (tmp_path / "plotsrv.yml").write_text(
        "description-settings:\n  views:\n    a:\n      description: "
        + json.dumps(text)
        + "\n"
    )
    assert client.get("/views").json()[0]["description"] == text
    html = client.get("/?view=a").text
    assert "<script>window.secret=1</script>" not in html
    assert "&lt;script&gt;window.secret=1&lt;/script&gt;" in html
    before = store.get_view_menu_revision()
    response = client.post(
        "/publish",
        json={"view_id": "bad", "kind": "artifact", "description": "x" * 2049},
    )
    assert response.status_code == 422
    assert store.get_view_menu_revision() == before


def test_watch_and_stream_registration_transport_plain_descriptions(client, tmp_path):
    from plotsrv.source_setup import watch_descriptor
    from plotsrv.cli_parser import WatchSpec
    from uuid import uuid4
    from plotsrv.streams.models import STREAM_PROTOCOL_VERSION

    (tmp_path / "plotsrv.yml").write_text(
        "description-settings:\n  views:\n    watched:\n      description: Configured watch purpose\n"
    )
    descriptor = watch_descriptor(
        WatchSpec("/not-present-on-server", view_id="watched")
    )
    assert descriptor.description == "Configured watch purpose"
    response = client.post(
        "/watch/register",
        json=dict(
            protocol_version=1,
            view_id="watched",
            label="Watched",
            client_id=uuid4().hex,
            description=descriptor.description,
        ),
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/stream/register",
        json=dict(
            protocol_version=STREAM_PROTOCOL_VERSION,
            view_id="streamed",
            label="Streamed",
            section="events",
            client_id=uuid4().hex,
            session_id=uuid4().hex,
            description="Accepted application events",
        ),
    )
    assert response.status_code == 200, response.text
    descriptions_by_id = {
        v["view_id"]: v["description"] for v in client.get("/views").json()
    }
    assert descriptions_by_id["streamed"] == "Accepted application events"


def test_observation_metadata_does_not_revert_newer_source_caption(client):
    from tests.test_observation_presentation import summary, accept

    register_catalogue(
        [ViewDescriptor("test", "Test", description="Old catalogue")], seal=False
    )
    store.register_view(view_id="test", description="New source explanation")
    accept(summary({"orders": 42}))
    assert client.get("/views").json()[0]["description"] == "New source explanation"


def test_async_publication_detaches_and_accounts_for_bounded_description(monkeypatch):
    from plotsrv.publishing.models import PublishTarget
    from types import SimpleNamespace

    tasks = []
    monkeypatch.setattr(
        publisher,
        "resolve_publish_target",
        lambda **kw: PublishTarget("remote", "127.0.0.1", 8000),
    )
    monkeypatch.setattr(
        publisher, "get_publish_worker", lambda: SimpleNamespace(submit=tasks.append)
    )
    publisher.publish_view({"orders": 42}, async_=True, description="x" * 1_000_000)
    assert len(tasks) == 1 and len(tasks[0].description) == 512
    assert tasks[0].estimated_bytes >= 4 * 512


def test_local_publication_explanation_uses_existing_store(client, monkeypatch):
    from plotsrv import server

    monkeypatch.setattr(server, "start_server", lambda **kw: None)
    monkeypatch.setattr(server, "_ensure_server_running", lambda *a, **kw: False)
    publisher.publish_view(
        {"orders": 42},
        view_id="business:local",
        mode="local",
        async_=False,
        description="Locally computed totals",
    )
    assert client.get("/views").json()[0]["description"] == "Locally computed totals"


@pytest.mark.parametrize("supported", [False, True])
def test_watch_description_uses_optional_receiver_capability(
    client, monkeypatch, tmp_path, supported
):
    from dataclasses import replace
    from types import SimpleNamespace
    from plotsrv import publisher_agent, ingestion
    from tests.test_remote_watch import connect_watcher, tick

    path = tmp_path / "events.txt"
    path.write_text("Accepted events")
    watcher = connect_watcher(monkeypatch, client, path)
    current = watcher.states[0]
    current.descriptor = replace(current.descriptor, description="Publisher purpose")
    monkeypatch.setattr(
        publisher_agent,
        "handshake",
        lambda *a, **kw: SimpleNamespace(
            server_generation=ingestion.state().generation,
            capabilities=["view-descriptions-v1"] if supported else [],
        ),
    )
    try:
        tick(watcher)
        tick(watcher)
        assert (
            store.get_artifact(view_id=current.descriptor.view_id).obj
            == "Accepted events"
        )
        assert store._VIEW_META[current.descriptor.view_id].description == (
            "Publisher purpose" if supported else None
        )
    finally:
        watcher.close()
