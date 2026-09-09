"""Bounded server interpretation of accepted JSON; never parses source logs.

Only the newest MAX_RECORDS accepted observations are eligible. Mappings are
fixed for a session and have stable presentation identities across restarts.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

MAX_RECORDS = 512
MAX_FIELDS = 32
PREFIX = "__plotsrv_http_"
METHODS = frozenset("GET HEAD POST PUT DELETE CONNECT OPTIONS TRACE PATCH".split())
UNITS = {"ns": 0.000001, "us": 0.001, "ms": 1.0, "s": 1000.0}
ROLES = frozenset(
    {"method", "path", "status", "route", "duration", "duration_unit", "timestamp"}
)
CONTROL = re.compile(r"[\x00-\x20\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def validate_override(value: Any) -> dict[str, Any] | bool | None:
    """Small server-owned per-ID mapping. Paths are JSON key lists, not files."""
    if value is None or value is False:
        return value
    if not isinstance(value, dict) or len(value) > len(ROLES) or set(value) - ROLES:
        raise ValueError("HTTP profile mapping has unsupported roles")
    if not {"method", "path", "status"} <= value.keys():
        raise ValueError("HTTP profile mapping requires method, path and status")
    out = {}
    for role, path in value.items():
        if role == "duration_unit":
            if not isinstance(path, str) or path not in UNITS:
                raise ValueError("HTTP duration unit must be ns, us, ms or s")
        elif (
            not isinstance(path, list)
            or not 1 <= len(path) <= 4
            or any(
                not isinstance(key, str) or not key or len(key) > 128 for key in path
            )
        ):
            raise ValueError("HTTP field paths require one to four bounded JSON keys")
        out[role] = list(path) if isinstance(path, list) else path
    if ("duration" in out) != ("duration_unit" in out):
        raise ValueError("HTTP duration requires both a field and an explicit unit")
    return out


def lookup(data: dict, path: list[str] | None) -> Any:
    value = data
    for key in path or []:
        if not isinstance(value, dict) or len(value) > MAX_FIELDS:
            return None
        value = value.get(key)
    return value if path else None


def timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        return None


def endpoint(value: Any) -> str | None:
    # Reject oversized input before regex/string work. Never infer route templates.
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 1024:
        return None
    clean = value.split("?", 1)[0].split("#", 1)[0]
    if CONTROL.search(clean):
        return None
    return clean


def request(data: dict, mapping: dict) -> dict | None:
    method, status, path = (
        lookup(data, mapping.get(k)) for k in ("method", "status", "path")
    )
    path = endpoint(path)
    if (
        not isinstance(method, str)
        or method not in METHODS
        or type(status) is not int
        or not 100 <= status <= 599
        or path is None
    ):
        return None
    return {"method": method, "status": status, "path": path}


def detect(data: dict) -> dict | None:
    event = data.get("event")
    if "log_schema_version" in data:
        if (
            type(data["log_schema_version"]) is not int
            or data["log_schema_version"] != 1
            or not isinstance(event, dict)
            or event.get("kind") != "http_request"
            or event.get("adapter") != "uvicorn"
        ):
            return None
        mapping = {k: ["http", k] for k in ("method", "path", "status", "route")}
        mapping.update(
            duration=["http", "duration_ms"],
            duration_unit="ms",
            timestamp=["event", "source_timestamp"],
        )
        mapping["observed"] = ["event", "publisher_observed_at"]
        mapping["adapter"] = True
        return mapping if request(data, mapping) else None
    # Two deliberately documented shapes; conflicting complete candidates are ambiguous.
    candidates = []
    for prefix in ([], ["http"]):
        mapping = {k: prefix + [k] for k in ("method", "path", "status", "route")}
        mapping.update(
            duration=prefix + ["duration_ms"],
            duration_unit="ms",
            timestamp=["timestamp"],
        )
        if request(data, mapping):
            candidates.append(mapping)
    return candidates[0] if len(candidates) == 1 else None


class HttpProfile:
    def __init__(self, override: Any = None):
        self.error = None
        try:
            self.mapping = validate_override(override)
        except ValueError:
            self.mapping = False
            self.error = (
                "Invalid server HTTP field mapping; raw stream remains available."
            )
        self.disabled = self.mapping is False
        self.identity: str | None = None
        self.rows: OrderedDict[int, dict | None] = OrderedDict()
        self.time_origin = "received"
        self.endpoint_origin = "path"

    def add(self, sequence: int, data: dict, received_at: datetime) -> None:
        if self.disabled:
            return
        if len(data) > MAX_FIELDS:
            # Uninspected keys must never impersonate a derived field, including
            # in rows accepted before recognition starts. Fail only the profile.
            self.disabled = True
            self.error = "HTTP interpretation stopped: a record exceeds the 32-field inspection bound. Raw stream remains available."
            self.rows.clear()
            return
        elif any(key.startswith(PREFIX) for key in data):
            # A source key can never impersonate or overwrite a derived column.
            self.disabled = True
            self.rows.clear()
            return
        else:
            projection = self._project(data, received_at)
        if projection is None and self.identity is None:
            return
        self.rows[sequence] = projection
        if len(self.rows) > MAX_RECORDS:
            self.rows.popitem(last=False)

    def _project(self, data: dict, received_at: datetime) -> dict | None:
        mapping = self.mapping or detect(data)
        if not mapping:
            return None
        if mapping.get("adapter") and (
            type(data.get("log_schema_version")) is not int
            or data.get("log_schema_version") != 1
            or any(
                lookup(data, ["raw", key]) is not False
                for key in ("partial", "truncated", "ambiguous")
            )
            or lookup(data, ["event", "kind"]) != "http_request"
            or lookup(data, ["event", "adapter"]) != "uvicorn"
        ):
            return None
        result = request(data, mapping)
        if result is None:
            return None
        if self.identity is None:
            self.mapping = mapping
            if timestamp(lookup(data, mapping.get("timestamp"))):
                self.time_origin = "event"
            elif timestamp(lookup(data, mapping.get("observed"))):
                self.time_origin = "observed"
            if endpoint(lookup(data, mapping.get("route"))):
                self.endpoint_origin = "route"
            identity = json.dumps(
                ["http-profile-v1", mapping, self.time_origin, self.endpoint_origin],
                sort_keys=True,
            )
            self.identity = hashlib.sha256(identity.encode()).hexdigest()[:16]
        result["endpoint"] = (
            endpoint(lookup(data, mapping.get("route")))
            if self.endpoint_origin == "route"
            else result["path"]
        )
        result["request"] = 1
        result["class"] = {
            1: "1xx informational",
            2: "2xx success",
            3: "3xx redirect",
            4: "4xx client error",
            5: "5xx server error",
        }[result["status"] // 100]
        result["time"] = (
            received_at.isoformat()
            if self.time_origin == "received"
            else timestamp(
                lookup(
                    data,
                    mapping.get(
                        "timestamp" if self.time_origin == "event" else "observed"
                    ),
                )
            )
        )
        duration = lookup(data, mapping.get("duration"))
        if type(duration) in (float, int) and 0 <= duration <= 1e15:
            converted = duration * UNITS[mapping["duration_unit"]]
            if math.isfinite(converted):
                result["duration"] = converted
        return result

    def evict(self, sequence: int) -> None:
        self.rows.pop(sequence, None)

    def describe(
        self, source_id: str, raw_columns: list[str], *, historical: bool = False
    ) -> dict:
        valid = [row for row in self.rows.values() if row]
        wide = (
            len(raw_columns) > 100
            or any(len(key) > 256 for key in raw_columns)
            or sum(map(len, raw_columns)) > 3000
        )
        reason = "No validated HTTP requests in the eligible retained window."
        if historical:
            reason = "HTTP presentations are unavailable for stored sessions and generic compact summaries; use raw history or summary controls."
        elif self.disabled:
            reason = (
                self.error
                or "HTTP interpretation is disabled or a source field conflicts with its derived column namespace."
            )
        elif wide:
            reason = "HTTP suggestions are unavailable: raw column names exceed the presentation size budget."
        if historical or self.disabled or not valid or wide:
            return {"version": 1, "recipes": [], "unavailable": reason}
        fields = {
            role: PREFIX + self.identity + "_" + role
            for role in (
                "request",
                "method",
                "path",
                "endpoint",
                "status",
                "class",
                "time",
            )
        }
        if any("duration" in row for row in valid):
            fields["duration"] = PREFIX + self.identity + "_duration"
        types = {
            field: (
                "number"
                if role in ("request", "status", "duration")
                else "datetime" if role == "time" else "text"
            )
            for role, field in fields.items()
        }
        labels = {
            fields[k]: v
            for k, v in {
                "request": "Validated HTTP request",
                "method": "Method",
                "path": "Request path (query removed)",
                "endpoint": (
                    "Provided route template"
                    if self.endpoint_origin == "route"
                    else "Request path (not a route template)"
                ),
                "status": "HTTP status",
                "class": "Status class",
                "time": self.time_origin.capitalize() + " time (UTC)",
                **({"duration": "Duration (ms)"} if "duration" in fields else {}),
            }.items()
        }
        scope = "Newest up to 512 accepted records still retained and loaded; validated requests only, not all traffic. Gaps may exist. Older HTTP summary history unavailable."
        return {
            "version": 1,
            "id": self.identity,
            "fields": fields,
            "types": types,
            "labels": labels,
            "first_sequence": next(iter(self.rows)),
            "request_count": len(valid),
            "inspected_count": len(self.rows),
            "scope": scope,
            "time_origin": self.time_origin,
            "recipes": recipes(
                source_id, fields, types, raw_columns, scope, self.time_origin
            ),
        }

    def projection(self, sequence: int) -> dict | None:
        row = self.rows.get(sequence)
        return dict(row) if row and self.identity and not self.disabled else None


def recipes(
    source_id: str, f: dict, types: dict, raw: list[str], scope: str, origin: str
) -> list[dict]:
    def spec(
        name: str,
        *,
        filters: list | None = None,
        plot: dict | None = None,
        group: str = "",
        sort: str = "time",
    ) -> dict:
        p = {
            "search": "",
            "filters": [
                {"field": f["request"], "op": "eq", "value": "1", "valueTo": ""}
            ]
            + (filters or []),
            "sort": [{"field": f[sort], "dir": "desc"}],
            "group": group,
            "columns": [f[k] for k in ("time", "method", "endpoint", "status", "class")]
            + ([f["duration"]] if "duration" in f else [])
            + raw,
            "hidden": raw + [f["request"], f["path"]],
            "mode": "plot+data" if plot else "table",
            "plot": {
                "type": "bar",
                "source": "table",
                "aggregation": "count",
                "categoryLimit": 10,
                "palette": "http",
                **(plot or {}),
            },
        }
        p["columns"] += [field for field in f.values() if field not in p["columns"]]
        required = [{"name": field, "type": typ} for field, typ in types.items()]
        return {
            "version": 1,
            "sourceId": source_id,
            "name": name,
            "caption": scope,
            "presentation": p,
            "requirements": {
                "fields": required,
                "plotFields": required,
                "plotSource": "table",
            },
        }

    result = [
        spec("Recent requests"),
        spec(
            "Errors",
            filters=[
                {"field": f["status"], "op": "gte", "value": "400", "valueTo": ""}
            ],
        ),
        spec(
            "Busiest endpoints",
            plot={
                "categoryField": f["endpoint"],
                "seriesField": f["class"],
                "sort": "value-desc",
                "display": "stacked",
                "title": "Retained requests by endpoint",
            },
        ),
        spec(
            "Traffic by status over time",
            plot={
                "type": "time-count",
                "xField": f["time"],
                "seriesField": f["class"],
                "xLabel": origin.capitalize() + " time (browser local)",
                "yLabel": "Retained request count",
                "showPoints": True,
            },
        ),
        spec(
            "Endpoint event activity",
            group=f["endpoint"],
            plot={
                "type": "scatter",
                "xField": f["time"],
                "yField": f["status"],
                "seriesField": f["class"],
                "xLabel": origin.capitalize() + " time (browser local)",
                "yLabel": "HTTP status",
                "title": "Request activity — filter an endpoint to focus",
            },
        ),
    ]
    if "duration" in f:
        duration_filter = [
            {"field": f["duration"], "op": "not_missing", "value": "", "valueTo": ""}
        ]
        result.extend(
            [
                spec(
                    "Latency distribution",
                    filters=duration_filter,
                    plot={
                        "type": "histogram",
                        "histogramField": f["duration"],
                        "bins": "20",
                        "xLabel": "Duration (ms)",
                    },
                ),
                spec(
                    "Latency over time",
                    filters=duration_filter,
                    plot={
                        "type": "scatter",
                        "xField": f["time"],
                        "yField": f["duration"],
                        "seriesField": f["class"],
                        "xLabel": origin.capitalize() + " time (browser local)",
                        "yLabel": "Duration (ms)",
                    },
                ),
                spec(
                    "Slowest retained requests",
                    filters=duration_filter,
                    sort="duration",
                ),
            ]
        )
    return result
