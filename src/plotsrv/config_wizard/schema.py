"""Role pages using existing config defaults and production value validators."""

from __future__ import annotations

import copy
from dataclasses import fields, replace
import ipaddress
from urllib.parse import urlsplit

from .. import config, settings
from ..connection_config import (
    get_publisher_sources,
    get_server_connection_config,
    ServerConnectionConfig,
)
from ..observations.models import ObservationBudget
from ..publishing.models import PublishTarget
from .draft import FIELDS, FieldSpec, model_default

PAGES = {
    name: []
    for name in (
        "storage",
        "freshness",
        "publisher",
        "server",
        "watch",
        "publish",
        "limits",
        "security",
        "checks",
    )
}


def add(
    page,
    key,
    path,
    label,
    kind,
    meaning,
    units="text",
    minimum=None,
    maximum=None,
    choices=(),
    default=None,
    per_view=False,
):
    if default is None:
        value = config._DEFAULTS.get(path[0], {})
        for part in path[1:]:
            value = value.get(part) if isinstance(value, dict) else None
        default = value
    spec = FieldSpec(
        key,
        tuple(path),
        label,
        kind,
        default,
        meaning,
        units,
        minimum,
        maximum,
        per_view,
        tuple(choices),
    )
    FIELDS[key] = spec
    PAGES[page].append(key)


for key, label, kind, units, low in (
    ("enabled", "Keep snapshots on disk", "bool", "on/off", None),
    ("watch_enabled", "Store watched-file snapshots", "bool", "on/off", None),
    ("root_dir", "Snapshot folder", "str", "config-relative path", None),
    ("max_snapshot_size_mb", "Maximum snapshot size", "float", "MiB", 0.001),
    (
        "default_keep_last",
        "Snapshots retained per view",
        "keep",
        "snapshots (off = unlimited)",
        None,
    ),
    (
        "default_min_store_interval",
        "Minimum interval between snapshots",
        "duration",
        "seconds or s/m/h/d; off = no interval",
        None,
    ),
):
    add(
        "storage",
        "storage_" + key,
        ("storage-settings", key),
        label,
        kind,
        "Server-side disk storage. Disabling storage retains these choices and does not disable in-memory stream summaries. Per-view values inherit the global policy.",
        units,
        low,
        per_view=key != "root_dir",
    )
for key, label, kind in (
    ("enabled", "Check freshness", "bool"),
    ("expected_every", "Expected update interval", "duration"),
    ("warn_after", "Warning threshold", "duration"),
    ("overdue_after", "Overdue threshold", "duration"),
):
    add(
        "freshness",
        "freshness_" + key,
        ("freshness-settings", key),
        label,
        kind,
        "Server freshness uses last data receipt, not event timestamps or snapshot age. An unset warning uses expected_every; an unset overdue threshold uses twice the warning. Per-view settings inherit global values.",
        "on/off" if kind == "bool" else "seconds or s/m/h/d; off = unset",
        per_view=True,
    )
for key, label, path, kind, default in (
    (
        "bind_host",
        "Bind host",
        ("bind", "host"),
        "str",
        model_default(ServerConnectionConfig, "bind_host"),
    ),
    (
        "bind_port",
        "Bind port",
        ("bind", "port"),
        "int",
        model_default(ServerConnectionConfig, "bind_port"),
    ),
    (
        "ingress_key",
        "Publisher key environment variable",
        ("ingestion", "bearer_token_env"),
        "env",
        None,
    ),
    (
        "allow_remote",
        "Allow remote publishers without a key",
        ("ingestion", "allow_remote_without_key"),
        "bool",
        False,
    ),
    ("admission", "Source admission", ("admission", "mode"), "str", "dynamic"),
):
    add(
        "server",
        key,
        ("server-settings", *path),
        label,
        kind,
        "Receiving server policy. No key on loopback is normal. Remote no-key exposure must be explicitly enabled on a trusted private endpoint. Locked admission needs a complete expected-ID list or explicit bootstrap after startup.",
        "port number" if key == "bind_port" else "on/off" if kind == "bool" else "text",
        1 if key == "bind_port" else None,
        65535 if key == "bind_port" else None,
        ("dynamic", "catalogue-locked") if key == "admission" else (),
        default,
    )
PAGES["publisher"].append("request_timeout")
for field in fields(ObservationBudget):
    key = field.name
    default = model_default(ObservationBudget, key)
    add(
        "publisher",
        "observe_" + key,
        ("publish-settings", "observe", key),
        key.replace("_", " ").capitalize(),
        "int" if type(default) is int else "float",
        "Publisher-only observe=True budget. Admission precedes detached capture; fixed production safety caps still apply. Capture milliseconds are cooperative, not a hard cancellation guarantee. Queue overload drops/coalesces observation work.",
        (
            "milliseconds"
            if key.endswith("_ms")
            else (
                "seconds"
                if key.endswith("_s")
                else "bytes" if "bytes" in key else "count"
            )
        ),
        default=default,
    )
for key in ("async_enabled", "max_pending_views", "max_pending_mb", "flush_timeout_s"):
    add(
        "publish",
        "live_" + key,
        ("publish-settings", "live", key),
        key.replace("_", " ").capitalize(),
        (
            "bool"
            if key == "async_enabled"
            else "int" if key == "max_pending_views" else "float"
        ),
        "Ordinary publisher process: async work coalesces the latest update per view. These bounds do not raise receiver limits. Observe=True keeps its separate bounded asynchronous path.",
        (
            "on/off"
            if key == "async_enabled"
            else (
                "MiB"
                if key.endswith("_mb")
                else "seconds" if key.endswith("_s") else "views"
            )
        ),
        None if key == "async_enabled" else 0 if key == "flush_timeout_s" else 0.001,
    )
for key in (
    "request_timeout_s",
    "retry_initial_delay_s",
    "retry_max_delay_s",
    "shutdown_drain_timeout_s",
):
    add(
        "publish",
        "stream_" + key,
        ("stream-settings", key),
        "Stream " + key.replace("_", " "),
        "float",
        "Stream publisher transport retry/drain settings. Remote watch uses its existing capped backoff; there is no independent watch retry setting to invent.",
        "seconds",
        0.001,
    )
add(
    "publish",
    "remote_stream_request_timeout_s",
    ("publisher-settings", "destination", "stream_request_timeout_s"),
    "Remote stream request timeout",
    "float",
    "Maximum wait for each stream HTTP request to the configured destination. Retry delays below are separate.",
    "seconds",
    0.001,
    300,
    default=model_default(PublishTarget, "stream_request_timeout_s"),
)
for key, kind, choices in (
    ("materialization", "str", ("auto", "memory", "file")),
    ("file_threshold_mb", "float", ()),
):
    add(
        "watch",
        "watch_" + key,
        ("watch-settings", key),
        key.replace("_", " ").capitalize(),
        kind,
        "Publisher/local watch representation. A remote receiver never opens the publisher path. Existing transfer and decoded-source bounds remain enforced.",
        "MiB" if kind == "float" else "choice",
        0.001 if kind == "float" else None,
        choices=choices,
    )
for key in ("max_concurrent", "wait_timeout_s"):
    add(
        "watch",
        "watch_" + key,
        ("watch-settings", "active_loads", key),
        key.replace("_", " ").capitalize(),
        "int" if key == "max_concurrent" else "float",
        "Local server file-backed preview admission; remote preview transfer has separate hard bounds.",
        "loads" if key == "max_concurrent" else "seconds",
        1 if key == "max_concurrent" else 0,
    )
for key in config._DEFAULTS["limits"]["published_objects"]:
    add(
        "limits",
        "limit_" + key,
        ("limits", "published_objects", key),
        key.replace("_", " ").capitalize(),
        "int",
        "Preparation/ingestion safety bound in the process using this config; neither publisher nor server can raise the other peer limits.",
        "bytes" if "bytes" in key else "count",
        1,
    )
add(
    "limits",
    "watch_max_mb",
    ("limits", "watched_files", "max_mb"),
    "Maximum watched-file read",
    "float",
    "Local read cap; remote transfer retains its smaller independent hard caps. Keep finite bounds for production.",
    "MiB",
    0.001,
)
for key in config._DEFAULTS["security-settings"]:
    add(
        "security",
        "security_" + key,
        ("security-settings", key),
        key.replace("_", " ").capitalize(),
        "bool",
        "Server-side route exposure/security. Tracebacks may reveal sensitive details. Keep administrative controls local; these settings are not dashboard authentication.",
        "on/off",
    )
add(
    "checks",
    "checks_enabled",
    ("checks-settings", "enabled"),
    "Enable configured checks",
    "bool",
    "Server-owned state/event rules. Use the existing checks-settings.rules schema; this wizard does not create a second rule language.",
    "on/off",
    default=True,
)
add(
    "checks",
    "webhook_cooldown",
    ("webhook-settings", "event_cooldown_s"),
    "Webhook event cooldown",
    "float",
    "Server notification cooldown. Existing destination URLs are hidden in review; headers use environment references. No webhook is sent while editing.",
    "seconds",
    1,
    86400,
    default=60,
)


def fields_for(page, draft, view_id=None):
    specs = [FIELDS[key] for key in PAGES[page]]
    if page == "publish":
        remote = bool(draft.value(FIELDS["destination"]))
        specs = [
            spec
            for spec in specs
            if spec.key
            != (
                "stream_request_timeout_s"
                if remote
                else "remote_stream_request_timeout_s"
            )
        ]
    if view_id is None:
        return specs
    result = []
    for spec in specs:
        if not spec.per_view:
            continue
        key = {
            "default_keep_last": "keep_last",
            "default_min_store_interval": "min_store_interval",
        }.get(spec.path[-1], spec.path[-1])
        default = True if key == "enabled" else draft.value(spec)
        if page == "freshness" and key == "enabled" and draft.role != "server":
            watched = view_id in {w.view_id for w in draft.watches()}
            configured = view_id in draft.section("freshness-settings").get("views", {})
            if watched and not configured:
                default = False
        result.append(
            replace(spec, path=(spec.path[0], "views", view_id, key), default=default)
        )
    return result


def loopback(host):
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return host == "localhost"


def validate_document(document, name, base, role):
    from .saving import SaveError
    from ..checks_config import parse_checks
    from ..webhook_config import parse_webhooks

    section = lambda key: settings.effective_section(
        document, key, name=name, strict=True
    )
    try:
        for page in (
            ("storage", "freshness", "server", "security", "checks", "watch", "limits")
            if role == "server"
            else (
                ("publisher", "publish", "watch", "limits")
                if role == "publisher"
                else tuple(PAGES)
            )
        ):
            for key in PAGES[page]:
                spec = FIELDS[key]
                node = section(spec.path[0])
                for part in spec.path[1:]:
                    if node is None and spec.path[:2] == (
                        "publisher-settings",
                        "destination",
                    ):
                        node = spec.default
                        break
                    if not isinstance(node, dict):
                        raise ValueError("Setting parent must be a mapping")
                    if part not in node:
                        node = spec.default
                        break
                    node = node[part]
                if node is not None:
                    spec.parse_config(node)
        if role != "server":
            pub = section("publisher-settings")
            get_publisher_sources(section=pub, base=base)
            raw = pub.get("destination")
            if raw is not None:
                if (
                    not isinstance(raw, dict)
                    or raw.keys()
                    - {
                        "url",
                        "bearer_token_env",
                        "request_timeout_s",
                        "stream_request_timeout_s",
                    }
                    or not raw.get("url")
                ):
                    raise ValueError("Invalid publisher destination")
                ref = FIELDS["bearer"].parse(raw.get("bearer_token_env") or "")
                target = PublishTarget(
                    kind="remote",
                    base_url=raw["url"],
                    **{
                        k: v
                        for k, v in raw.items()
                        if k not in ("url", "bearer_token_env")
                    },
                )
                if (
                    ref
                    and urlsplit(target.base_url).scheme != "https"
                    and not loopback(target.host)
                ):
                    raise ValueError(
                        "Bearer publication requires HTTPS outside loopback"
                    )
            elif role == "publisher":
                raise ValueError("Publisher destination URL is required")
            streams = section("stream-settings")
            initial = streams.get(
                "retry_initial_delay_s",
                config._DEFAULTS["stream-settings"]["retry_initial_delay_s"],
            )
            maximum = streams.get(
                "retry_max_delay_s",
                config._DEFAULTS["stream-settings"]["retry_max_delay_s"],
            )
            if float(maximum) < float(initial):
                raise ValueError(
                    "Stream maximum retry delay must be at least the initial delay"
                )
            ObservationBudget.from_mapping(
                section("publish-settings").get("observe", {})
            )
        if role != "publisher":
            server = copy.deepcopy(section("server-settings"))
            ingress = server.get("ingestion", {})
            ref = FIELDS["ingress_key"].parse(ingress.get("bearer_token_env") or "")
            ingress.pop("bearer_token_env", None)
            connection = get_server_connection_config(section=server)
            if (
                not loopback(connection.bind_host)
                and not ref
                and not connection.allow_remote_without_key
            ):
                raise ValueError(
                    "Non-loopback hosting requires a key reference or explicit remote no-key exposure"
                )
            webhook = parse_webhooks(section("webhook-settings"), resolve_secrets=False)
            parse_checks(
                section("checks-settings"),
                destinations=tuple(d.name for d in webhook.destinations),
            )
            for sec in ("storage-settings", "freshness-settings"):
                raw = section(sec)
                views = raw.get("views", {})
                if not isinstance(views, dict) or len(views) > 1024:
                    raise ValueError("Per-view configuration exceeds limits")
                for vid, row in [(None, raw), *views.items()]:
                    if not isinstance(row, dict):
                        raise ValueError("Per-view settings must be a mapping")
                    for key, val in row.items():
                        original_key = {
                            "keep_last": "default_keep_last",
                            "min_store_interval": "default_min_store_interval",
                            "error_after": "overdue_after",
                        }.get(key, key)
                        field_key = (
                            "storage_" if sec == "storage-settings" else "freshness_"
                        ) + original_key
                        if field_key in FIELDS and val is not None:
                            FIELDS[field_key].parse_config(val)
                    if sec == "freshness-settings":
                        effective = {**raw, **row}
                        warn = config._parse_duration_seconds(
                            effective.get("warn_after")
                        )
                        if warn is None:
                            warn = config._parse_duration_seconds(
                                effective.get("expected_every")
                            )
                        # Match runtime per-view precedence, including the legacy
                        # alias and an explicitly unset per-view threshold.
                        if vid is not None and "overdue_after" in row:
                            overdue_value = row["overdue_after"]
                        elif vid is not None and "error_after" in row:
                            overdue_value = row["error_after"]
                        else:
                            overdue_value = raw.get("overdue_after")
                            if overdue_value is None:
                                overdue_value = raw.get("error_after")
                        overdue = config._parse_duration_seconds(overdue_value)
                        if warn and overdue and warn > overdue:
                            raise ValueError(
                                "Freshness overdue threshold must not precede warning threshold"
                            )
    except (ValueError, TypeError, OverflowError) as error:
        # Production validators use fixed field names/reasons, never source lines.
        raise SaveError("Invalid configuration: " + str(error)) from None


def review_projection(document, name, role):
    """Whitelist managed values; never echo arbitrary YAML/comments or webhook URLs."""
    from .saving import assign

    output = {}
    pages = (
        ("storage", "freshness", "server", "watch", "limits", "security", "checks")
        if role == "server"
        else (
            ("publisher", "publish", "watch", "limits")
            if role == "publisher"
            else tuple(PAGES)
        )
    )
    keys = {key for page in pages for key in PAGES[page]}
    if role != "server":
        keys.update(("destination", "bearer", "target"))
    for key in sorted(keys):
        spec = FIELDS[key]
        node = settings.effective_section(document, spec.path[0], name=name)
        found = True
        for part in spec.path[1:]:
            if not isinstance(node, dict) or part not in node:
                found = False
                break
            node = node[part]
        if found:
            # Values were validated on the proposed document; old invalid secrets
            # in destination fields are hidden instead of echoed in the diff.
            try:
                parsed = spec.parse_config(node)
                assign(output, spec.path, parsed)
            except ValueError:
                assign(output, spec.path, "<invalid value hidden>")
    for section_key, keys2 in (
        ("publisher-settings", ("discovery", "watch")),
        ("server-settings", ("admission",)),
        ("storage-settings", ("views",)),
        ("freshness-settings", ("views",)),
    ):
        if (
            role == "publisher"
            and section_key != "publisher-settings"
            or role == "server"
            and section_key == "publisher-settings"
        ):
            continue
        sec = settings.effective_section(document, section_key, name=name)
        for key in keys2:
            if key in sec:
                # These schema-owned collections contain source/identity/policy,
                # not secrets. Filter fields rather than copying unknown additions.
                allowed = (
                    {
                        "target",
                        "selection",
                        "exact_selection",
                        "additional_ids",
                        "include_pruned",
                    }
                    if key == "discovery"
                    else (
                        {"mode", "allowed_ids"}
                        if key == "admission"
                        else (
                            {
                                "path",
                                "view_id",
                                "label",
                                "section",
                                "read_mode",
                                "materialization",
                            }
                            if key == "watch"
                            else {
                                "enabled",
                                "watch_enabled",
                                "keep_last",
                                "min_store_interval",
                                "max_snapshot_size_mb",
                                "expected_every",
                                "warn_after",
                                "overdue_after",
                                "error_after",
                            }
                        )
                    )
                )
                value = sec[key]

                def clean(row):
                    return (
                        {k: v for k, v in row.items() if k in allowed}
                        if isinstance(row, dict)
                        else "<unsupported>"
                    )

                cleaned = (
                    [clean(row) for row in value]
                    if key == "watch" and isinstance(value, list)
                    else (
                        {vid: clean(row) for vid, row in value.items()}
                        if key == "views" and isinstance(value, dict)
                        else clean(value)
                    )
                )
                assign(output, (section_key, key), cleaned)
    return output


# Additional existing snapshot controls stay in the same storage form.
for key, kind, label, choices in (
    ("enabled", "bool", "Keep the latest stored view", ()),
    ("restore_on_startup", "bool", "Restore latest views at server startup", ()),
    ("restore_scope", "str", "Latest restore scope", ("discovered", "all", "none")),
):
    add(
        "storage",
        "latest_" + key,
        ("storage-settings", "latest", key),
        label,
        kind,
        "Server snapshot/latest persistence. Storage remains the master switch. Restoring content never enlarges a locked admission catalogue.",
        "on/off" if kind == "bool" else "choice",
        choices=choices,
    )
for key in ("max_pending_tasks", "max_pending_mb"):
    add(
        "storage",
        "storage_" + key,
        ("storage-settings", key),
        key.replace("_", " ").capitalize(),
        "int" if key == "max_pending_tasks" else "float",
        "Server-side best-effort storage queue bound; this does not raise producer queue limits.",
        "tasks" if key == "max_pending_tasks" else "MiB",
        minimum=1 if key == "max_pending_tasks" else 0.001,
    )
# Keep the core publisher route short; the other capture limits remain editable
# through Advanced / Publish using the very same production budget model.
_core = {
    "request_timeout",
    "observe_view_interval_s",
    "observe_process_interval_s",
    "observe_max_pending",
}
PAGES["publish"].extend(key for key in PAGES["publisher"] if key not in _core)
PAGES["publisher"][:] = [key for key in PAGES["publisher"] if key in _core]
