from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_publisher_transport():
    from plotsrv.publishing.transport import reset_transport

    reset_transport()
    yield
    reset_transport()


@pytest.fixture
def publisher_payload_transport(monkeypatch):
    """Payload/worker unit tests isolate negotiation, covered by transport tests."""
    import urllib.request
    from plotsrv.contracts import ProtocolCapabilities
    from plotsrv.publishing import transport

    monkeypatch.setattr(
        transport,
        "handshake",
        lambda *args, **kwargs: ProtocolCapabilities(
            server_generation="test", dashboard_scope="test", capabilities=("publish",)
        ),
    )
    monkeypatch.setattr(
        transport,
        "_open",
        lambda request, *, timeout: urllib.request.urlopen(request, timeout=timeout),
    )
