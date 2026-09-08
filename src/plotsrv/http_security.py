from __future__ import annotations

import ipaddress

from fastapi import HTTPException, Request


def _client_ip(request: Request) -> str | None:
    client = request.client
    if client is None:
        return None
    return client.host


def _is_loopback_ip(value: str | None) -> bool:
    if not value:
        return False
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def require_local_request(request: Request) -> None:
    if any(key in request.headers for key in ("forwarded", "x-forwarded-for", "x-forwarded-host", "authorization")):
        raise HTTPException(status_code=403, detail="Direct local administration only")
    if request.method not in ("GET", "HEAD", "OPTIONS") and "origin" in request.headers:
        from urllib.parse import urlsplit
        origin = urlsplit(request.headers["origin"])
        if origin.scheme != request.url.scheme or origin.netloc != request.url.netloc:
            raise HTTPException(status_code=403, detail="Same-origin local administration only")
    host = _client_ip(request)
    if not _is_loopback_ip(host):
        raise HTTPException(status_code=403, detail="Local access only")
