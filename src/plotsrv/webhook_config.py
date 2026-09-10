"""Small server-owned webhook destination configuration; never telemetry-driven."""

from dataclasses import dataclass, field
import ipaddress
import math
import os
import re
from urllib.parse import urlsplit

MAX_DESTINATIONS = 8
MAX_REFERENCES = 2


def url(value, *, dashboard=False):
    try:
        if (
            type(value) is not str
            or not value
            or len(value) > 2048
            or any(ord(c) < 33 or ord(c) > 126 for c in value)
        ):
            raise ValueError
        parts = urlsplit(value)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
            or parts.port == 0
            or (dashboard and parts.query)
        ):
            raise ValueError
        return value
    except (ValueError, UnicodeError):
        raise ValueError("invalid webhook URL configuration") from None


@dataclass(frozen=True, slots=True)
class Destination:
    name: str
    url: str = field(repr=False)
    headers: tuple = field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    destinations: tuple = ()
    event_cooldown_s: float = 60
    dashboard_url: str | None = None


def parse_webhooks(section, *, resolve_secrets=True):
    if type(section) is not dict or section.keys() - {
        "destinations",
        "event_cooldown_s",
        "dashboard_url",
    }:
        raise ValueError("invalid webhook-settings fields")
    rows = section.get("destinations", {})
    if type(rows) is not dict or len(rows) > MAX_DESTINATIONS:
        raise ValueError(
            "webhook destinations must be a mapping of at most eight names"
        )
    cooldown = section.get("event_cooldown_s", 60)
    if (
        type(cooldown) not in (int, float)
        or not 1 <= cooldown <= 86400
        or not math.isfinite(cooldown)
    ):
        raise ValueError("webhook event cooldown must be between 1 and 86400 seconds")
    dashboard = section.get("dashboard_url")
    if dashboard is not None:
        dashboard = url(dashboard, dashboard=True)
    destinations = []
    for name, row in rows.items():
        if type(name) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("invalid webhook destination name")
        if (
            type(row) is not dict
            or row.keys() - {"url", "headers_env"}
            or "url" not in row
        ):
            raise ValueError("invalid webhook destination fields")
        address = url(row["url"])
        headers = row.get("headers_env", {})
        if type(headers) is not dict or len(headers) > 8:
            raise ValueError("webhook headers_env must have at most eight entries")
        resolved, names, size = [], set(), 0
        for header, env in headers.items():
            if (
                type(header) is not str
                or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}", header)
                or header.lower() in names
                or header.lower()
                in {
                    "host",
                    "content-length",
                    "transfer-encoding",
                    "connection",
                    "content-type",
                    "content-encoding",
                    "accept-encoding",
                    "proxy-authorization",
                    "proxy-connection",
                    "trailer",
                    "te",
                    "upgrade",
                    "expect",
                    "idempotency-key",
                    "x-plotsrv-event-id",
                }
            ):
                raise ValueError("invalid or reserved webhook header")
            names.add(header.lower())
            if type(env) is not str or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]{0,127}", env
            ):
                raise ValueError("invalid webhook header environment reference")
            # Configuration review validates references without reading their values.
            secret = os.environ.get(env) if resolve_secrets else "unresolved-reference"
            if (
                not secret
                or len(secret) > 4096
                or not secret.strip()
                or any(ord(c) < 32 or ord(c) > 126 for c in secret)
            ):
                raise ValueError("webhook header secret is missing or invalid")
            size += len(header) + len(secret)
            if size > 8192:
                raise ValueError("webhook header secrets exceed the aggregate limit")
            resolved.append((header, secret))
        if resolved and urlsplit(address).scheme == "http":
            try:
                loopback = ipaddress.ip_address(urlsplit(address).hostname).is_loopback
            except ValueError:
                loopback = False
            if not loopback:
                raise ValueError(
                    "webhook secret headers require HTTPS or a numeric loopback URL"
                )
        destinations.append(Destination(name, address, tuple(resolved)))
    return WebhookConfig(tuple(destinations), float(cooldown), dashboard)
