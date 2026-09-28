"""Compact HTTP failure logging for the default server mode."""

from __future__ import annotations

import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send


_LOG = logging.getLogger("uvicorn.error")
_MAX_PATH_CHARS = 2048


class FailureRequestLogger:
    """Log failed HTTP responses without recording routine successful traffic."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_logged(message: Message) -> None:
            if message["type"] == "http.response.start":
                status = int(message["status"])
                if status >= 400:
                    path = scope.get("path", "")
                    if len(path) > _MAX_PATH_CHARS:
                        path = path[:_MAX_PATH_CHARS] + "…"
                    client = scope.get("client")
                    address = client[0] if client else "unknown"
                    _LOG.log(
                        logging.ERROR if status >= 500 else logging.WARNING,
                        "HTTP %s %s %s from %s",
                        status,
                        json.dumps(scope.get("method", "?"), ensure_ascii=True),
                        json.dumps(path, ensure_ascii=True),
                        json.dumps(address, ensure_ascii=True),
                    )
            await send(message)

        await self.app(scope, receive, send_logged)
