"""Temporary editor routes, deliberately separate from the production app."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
from time import monotonic
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.requests import ClientDisconnect

from ..config_wizard.saving import SaveError
from .uploads import MAX_IMAGE_BYTES

STATIC = Path(__file__).resolve().parents[1] / "static"
SESSION_SECONDS = 3600


def browser_origin(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise SaveError(
            "Origin must be an exact HTTP(S) origin without a path or credentials."
        )
    try:
        parsed.port
    except ValueError:
        raise SaveError("Invalid origin port.") from None
    return value.rstrip("/")


async def body(request, limit):
    result = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(result) + len(chunk) > limit:
                    raise SaveError("Request exceeds the upload/input limit.")
                result.extend(chunk)
    except (TimeoutError, ClientDisconnect):
        raise SaveError("Request body timed out.") from None
    return bytes(result)


def create_app(draft, *, origin=None, token=None, on_close=None):
    origin = browser_origin(origin) if origin is not None else None
    authority = urlsplit(origin).netloc if origin is not None else None
    token = token or secrets.token_urlsafe(32)
    expires = monotonic() + SESSION_SECONDS
    busy = False
    recent = []

    def close():
        draft.closed = True
        draft.images.clear()
        if on_close:
            on_close()

    @asynccontextmanager
    async def lifespan(app):
        timer = asyncio.get_running_loop().call_later(SESSION_SECONDS, close)
        try:
            yield
        finally:
            timer.cancel()
            close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # The token is never returned by HTTP or interpolated into HTML/URLs.
    app.state.capability = token

    @app.middleware("http")
    async def gate(request: Request, call_next):
        nonlocal busy
        response = None
        # A bind address is not a browser hostname: wildcard binds and SSH port
        # forwarding must work without an explicit external-origin configuration.
        # --origin remains an optional pin for deployments that want one.
        expected_origin = (
            origin or f"{request.url.scheme}://{request.headers.get('host', '')}"
        )
        if len(request.headers.getlist("host")) != 1 or (
            authority is not None and request.headers.get("host") != authority
        ):
            response = Response("Invalid Host", status_code=403)
        elif request.headers.get("origin") not in (None, expected_origin):
            response = Response("Invalid Origin", status_code=403)
        elif request.scope.get("query_string"):
            response = Response("Query parameters are not supported", status_code=400)
        protected = request.scope["path"].startswith("/api/")
        if response is None and protected:
            supplied = request.headers.get("x-plotsrv-ui-session", "")
            if (
                len(supplied) > 128
                or not supplied.isascii()
                or not secrets.compare_digest(supplied, token)
                or draft.closed
                or monotonic() >= expires
            ):
                response = Response(
                    "Editor session is invalid or expired", status_code=403
                )
            elif request.method != "GET" and (
                request.headers.get("origin") != expected_origin
                or request.headers.get("x-plotsrv-ui-action") != "edit"
            ):
                response = Response("Invalid mutation origin/action", status_code=403)
            elif busy:
                response = Response(
                    "An editor operation is already running", status_code=409
                )
            else:
                now = monotonic()
                recent[:] = [stamp for stamp in recent if now - stamp < 1]
                if len(recent) >= 20:
                    response = Response("Please slow down", status_code=429)
                else:
                    recent.append(now)
        if response is None:
            if protected:
                busy = True
            try:
                response = await call_next(request)
            finally:
                if protected:
                    busy = False
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-src 'self' about:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            }
        )
        return response

    @app.exception_handler(SaveError)
    async def invalid(request, error):
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.exception_handler(OSError)
    async def filesystem_error(request, error):
        return JSONResponse(
            {
                "error": "File operation failed. Check permissions, asset directory and free space. The config was not replaced."
            },
            status_code=400,
        )

    manifest = json.loads((STATIC / "dist" / "manifest.json").read_text())
    asset_names = {
        manifest["css"],
        manifest["customiser_css"],
        manifest["customiser_js"],
    }
    # Package images only; no arbitrary directories and no production JS bundle.
    asset_names.update("/static/" + p.name for p in STATIC.glob("*.png") if p.is_file())
    asset_names.update(
        {
            "/static/icons/header-settings.png",
            "/static/icons/header-fullscreen.png",
        }
    )

    @app.get("/")
    async def index():
        from .page import page

        return HTMLResponse(page(manifest))

    @app.get("/static/{path:path}")
    async def asset(path: str):
        url = "/static/" + path
        if url not in asset_names:
            return Response(status_code=404)
        file = STATIC / path
        kind = (
            "text/css"
            if path.endswith(".css")
            else "text/javascript" if path.endswith(".js") else "image/png"
        )
        return Response(file.read_bytes(), media_type=kind)

    @app.get("/api/state")
    async def state():
        return draft.state()

    @app.get("/api/preview")
    async def preview():
        return HTMLResponse(
            draft.preview().replace(
                "</head>",
                '<link rel="stylesheet" href="'
                + manifest["customiser_css"]
                + '"></head>',
            )
        )

    @app.get("/api/image/{key}")
    async def image(key: str):
        if key not in ("logo", "favicon"):
            return Response(status_code=404)
        staged = draft.images.staged.get(key)
        raw = staged[1] if staged else draft.images.existing(draft.values[key])
        return (
            Response(raw, media_type="image/png") if raw else Response(status_code=204)
        )

    async def json_body(request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise SaveError("Expected JSON input.")
        try:
            value = json.loads(await body(request, 8192))
            if type(value) is not dict:
                raise ValueError
            return value
        except (ValueError, RecursionError, UnicodeError):
            raise SaveError("Invalid bounded JSON input.") from None

    @app.post("/api/draft")
    async def change(request: Request):
        draft.change(await json_body(request))
        return draft.state()

    @app.post("/api/upload/{key}")
    async def upload(key: str, request: Request):
        draft.upload(
            key,
            await body(request, MAX_IMAGE_BYTES),
            request.headers.get("x-image-name", ""),
        )
        return draft.state()

    @app.post("/api/review")
    async def review(request: Request):
        if await json_body(request) != {}:
            raise SaveError("Unexpected review fields.")
        return draft.prepare()

    @app.post("/api/save")
    async def finish(request: Request):
        value = await json_body(request)
        if set(value) != {"review_id"} or type(value["review_id"]) is not str:
            raise SaveError("Confirm the reviewed draft.")
        result = draft.finish(value["review_id"])
        asyncio.get_running_loop().call_later(0.5, close)
        return result

    @app.post("/api/cancel")
    async def cancel(request: Request):
        if await json_body(request) != {}:
            raise SaveError("Unexpected cancel fields.")
        close()
        return {"message": "Cancelled. Config and existing assets were not changed."}

    return app
