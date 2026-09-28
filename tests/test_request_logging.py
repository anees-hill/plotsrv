from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plotsrv.request_logging import FailureRequestLogger


def test_default_logs_each_failure_but_no_success_or_query(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()

    @app.get("/ok")
    def ok():
        return {"ok": True}

    @app.get("/bad")
    def bad():
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="bad")

    @app.get("/broken")
    def broken():
        raise RuntimeError("broken")

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        client = TestClient(FailureRequestLogger(app), raise_server_exceptions=False)
        assert client.get("/ok?token=secret").status_code == 200
        assert client.get("/bad?token=secret").status_code == 422
        assert client.get("/missing?token=secret").status_code == 404
        assert client.get("/broken?token=secret").status_code == 500

    records = [record for record in caplog.records if record.name == "uvicorn.error"]
    assert [(record.levelno, record.getMessage().split()[:3]) for record in records] == [
        (logging.WARNING, ["HTTP", "422", '"GET"']),
        (logging.WARNING, ["HTTP", "404", '"GET"']),
        (logging.ERROR, ["HTTP", "500", '"GET"']),
    ]
    assert '"/bad"' in records[0].getMessage()
    assert "from \"testclient\"" in records[0].getMessage()
    assert all("secret" not in record.getMessage() for record in records)


def test_failure_path_is_escaped_and_bounded(caplog: pytest.LogCaptureFixture) -> None:
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    scope = {
        "type": "http", "path": "/" + "a" * 2200 + "\nlog-injection",
        "method": "GET", "client": ("127.0.0.1", 1234),
    }

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        asyncio.run(FailureRequestLogger(app)(scope, receive, send))
        scope["path"] = "/bad\nlog-injection"
        asyncio.run(FailureRequestLogger(app)(scope, receive, send))

    lines = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error"]
    assert "log-injection" not in lines[0]
    assert len(lines[0]) < 2200
    assert "\\nlog-injection" in lines[1]
    assert "\n" not in lines[1]


@pytest.mark.parametrize("quiet,verbose,level,access", [
    (False, False, "info", False),
    (True, False, "warning", False),
    (False, True, "info", True),
    (True, True, "info", True),
])
def test_attached_server_log_modes(monkeypatch, quiet, verbose, level, access):
    import uvicorn
    from plotsrv import server as server_mod

    captured = {}

    def fake_run(self):
        captured["config"] = self.config

    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    server_mod._run_server("127.0.0.1", 8000, quiet, verbose)
    cfg = captured["config"]
    assert cfg.log_level == level
    assert cfg.access_log is access
    assert (cfg.app is server_mod.app) is verbose
    assert isinstance(cfg.app, FailureRequestLogger) is (not verbose)
