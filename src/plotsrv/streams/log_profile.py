"""Conservative, bounded presentations for common Python application logs."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import hashlib
import json
import re

from .http_profile import (
    MAX_FIELDS,
    MAX_RECORDS,
    ProfileBudget,
    projection_cost,
    timestamp,
)

PREFIX = "__plotsrv_log_"
LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
LOGGER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*")
STAMP = re.compile(
    r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d{1,6})?(?:Z|[+-]\d\d:\d\d)?"
)
TEXT = re.compile(
    r"(?P<stamp>\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d{1,6})?(?:Z|[+-]\d\d:\d\d)?)"
    r"\s+-\s+(?P<logger>[A-Za-z_][A-Za-z_0-9.]*)\s+-\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+-\s+(?P<message>[^\r\n]{1,4096})"
)
DEFAULT_TEXT = re.compile(
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):"
    r"(?P<logger>[A-Za-z_][A-Za-z_0-9.]*):(?P<message>[^\r\n]{1,4096})"
)


def log_time(value: object) -> tuple[bool, str | None]:
    """Accept a real ISO clock value; use receipt time if its zone is unknown."""
    if not isinstance(value, str) or len(value) > 40 or not STAMP.fullmatch(value):
        return False, None
    normalized = value.replace(",", ".")
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return False, None
    return True, timestamp(normalized)


def detect(data: dict) -> tuple[str, dict] | None:
    """Require a complete known shape; never infer arbitrary level/message pairs."""
    if "log_schema_version" in data:
        event, raw = data.get("event"), data.get("raw")
        if (
            type(data.get("log_schema_version")) is not int
            or data.get("log_schema_version") != 1
            or not isinstance(event, dict)
            or event.get("adapter") not in ("text", "uvicorn")
            or event.get("kind") != "text"
            or not isinstance(raw, dict)
            or any(
                raw.get(flag) is not False
                for flag in ("partial", "truncated", "ambiguous")
            )
            or not isinstance(raw.get("text"), str)
        ):
            return None
        line = raw["text"].strip()
        match = TEXT.fullmatch(line) or DEFAULT_TEXT.fullmatch(line)
        if not match:
            return None
        values = match.groupdict()
        if len(values["logger"]) > 128 or not LOGGER.fullmatch(values["logger"]):
            return None
        stamp = values.get("stamp")
        valid_time, source_time = log_time(stamp) if stamp else (True, None)
        if not valid_time:
            return None
        return "python_text", {
            "level": values["level"],
            "logger": values["logger"],
            "message": values["message"],
            "time": source_time,
        }
    if all(key in data for key in ("method", "path", "status")) or "http" in data:
        return None
    candidates = []
    for keys in (
        ("timestamp", "level", "logger", "message"),
        ("asctime", "levelname", "name", "message"),
    ):
        if not all(key in data for key in keys):
            continue
        stamp, level, logger, message = (data[key] for key in keys)
        valid_time, source_time = log_time(stamp)
        if (
            valid_time
            and isinstance(level, str)
            and level in LEVELS
            and isinstance(logger, str)
            and len(logger) <= 128
            and LOGGER.fullmatch(logger)
            and isinstance(message, str)
            and 0 < len(message) <= 4096
        ):
            candidates.append(
                (
                    "python_json:" + ",".join(keys),
                    {
                        "time": source_time,
                        "level": level,
                        "logger": logger,
                        "message": message,
                    },
                )
            )
    return candidates[0] if len(candidates) == 1 else None


class LogProfile:
    def __init__(self, *, budget: ProfileBudget | None = None):
        self.budget = budget
        self.retained_cost = 0
        self.rows: OrderedDict[int, dict | None] = OrderedDict()
        self.identity: str | None = None
        self.kind: str | None = None
        self.time_origin = "received"
        self.disabled = False
        self.error: str | None = None

    def add(self, sequence: int, data: dict, received_at: datetime) -> None:
        if self.disabled:
            return
        if len(data) > MAX_FIELDS or any(key.startswith(PREFIX) for key in data):
            self.disabled = True
            self.error = "Log interpretation stopped: a record exceeds inspection bounds or conflicts with derived fields."
            self.clear()
            return
        found = detect(data)
        if self.kind is None and found:
            self.kind = found[0]
            self.time_origin = "event" if found[1]["time"] else "received"
            identity = json.dumps(["log-profile-v1", self.kind, self.time_origin])
            self.identity = hashlib.sha256(identity.encode()).hexdigest()[:16]
        row = None
        if found and found[0] == self.kind:
            row = dict(found[1])
            row["time"] = (
                row["time"] if self.time_origin == "event" else received_at.isoformat()
            )
            row["event"] = 1
        if self.kind is None:
            return
        if sequence in self.rows:
            self.evict(sequence)
        elif len(self.rows) >= MAX_RECORDS:
            self.evict(next(iter(self.rows)))
        cost = projection_cost(row)
        if self.budget is not None and not self.budget.acquire(cost):
            self.disabled = True
            self.error = "Log interpretation stopped: the shared server projection memory budget is full."
            self.clear()
            return
        self.retained_cost += cost
        self.rows[sequence] = row

    def evict(self, sequence: int) -> None:
        if sequence in self.rows:
            cost = projection_cost(self.rows.pop(sequence))
            self.retained_cost -= cost
            if self.budget is not None:
                self.budget.used -= cost

    def clear(self) -> None:
        if self.budget is not None:
            self.budget.used -= self.retained_cost
        self.retained_cost = 0
        self.rows.clear()

    def projection(self, sequence: int) -> dict | None:
        row = self.rows.get(sequence)
        return dict(row) if row and not self.disabled else None

    def describe(
        self, source_id: str, raw_columns: list[str], *, historical: bool = False
    ) -> dict:
        valid = [row for row in self.rows.values() if row]
        wide = (
            len(raw_columns) > 100
            or any(len(key) > 256 for key in raw_columns)
            or sum(map(len, raw_columns)) > 3000
        )
        if historical or self.disabled or wide or not valid:
            return {
                "version": 1,
                "recipes": [],
                "unavailable": self.error
                or "No validated Python log events in the eligible retained window.",
            }
        fields = {
            role: PREFIX + self.identity + "_" + role
            for role in ("event", "time", "level", "logger", "message")
        }
        types = {
            field: (
                "number"
                if role == "event"
                else "datetime" if role == "time" else "text"
            )
            for role, field in fields.items()
        }
        time_label = (
            "Event time (UTC)" if self.time_origin == "event" else "Received time (UTC)"
        )
        labels = {
            fields[role]: label
            for role, label in {
                "event": "Validated log event",
                "time": time_label,
                "level": "Level",
                "logger": "Logger",
                "message": "Message",
            }.items()
        }
        scope = "Newest up to 512 accepted records still retained and loaded; validated Python log events only. Gaps may exist."
        return {
            "version": 1,
            "kind": self.kind,
            "label": "Python application log",
            "id": self.identity,
            "fields": fields,
            "types": types,
            "labels": labels,
            "first_sequence": next(iter(self.rows)),
            "event_count": len(valid),
            "inspected_count": len(self.rows),
            "scope": scope,
            "time_origin": self.time_origin,
            "recipes": recipes(
                source_id, fields, types, raw_columns, scope, self.time_origin
            ),
        }


def recipes(
    source_id: str, f: dict, types: dict, raw: list[str], scope: str, origin: str
) -> list[dict]:
    def spec(
        name: str, *, filters: list | None = None, plot: dict | None = None
    ) -> dict:
        columns = (
            [f[k] for k in ("time", "level", "logger", "message")] + raw + [f["event"]]
        )
        required = [{"name": field, "type": typ} for field, typ in types.items()]
        return {
            "version": 1,
            "sourceId": source_id,
            "name": name,
            "caption": scope,
            "presentation": {
                "search": "",
                "filters": [
                    {"field": f["event"], "op": "eq", "value": "1", "valueTo": ""}
                ]
                + (filters or []),
                "sort": [{"field": f["time"], "dir": "desc"}],
                "group": "",
                "columns": columns,
                "hidden": raw + [f["event"]],
                "mode": "plot+data" if plot else "table",
                "plot": {
                    "type": "bar",
                    "source": "table",
                    "aggregation": "count",
                    "categoryLimit": 10,
                    **(plot or {}),
                },
            },
            "requirements": {
                "fields": required,
                "plotFields": required,
                "plotSource": "table",
            },
        }

    return [
        spec("Recent log events"),
        spec(
            "Warnings and errors",
            filters=[
                {
                    "field": f["level"],
                    "op": "in",
                    "value": "WARNING\nERROR\nCRITICAL",
                    "valueTo": "",
                }
            ],
        ),
        spec(
            "Events by level over time",
            plot={
                "type": "time-count",
                "xField": f["time"],
                "seriesField": f["level"],
                "xLabel": origin.capitalize() + " time (browser local)",
                "yLabel": "Retained event count",
                "showPoints": True,
            },
        ),
        spec(
            "Busiest loggers",
            plot={
                "categoryField": f["logger"],
                "seriesField": f["level"],
                "sort": "value-desc",
                "display": "stacked",
                "title": "Retained events by logger",
            },
        ),
    ]
