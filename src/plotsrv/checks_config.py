"""Server-owned declarative checks. No expressions or publisher policy overrides."""

from dataclasses import dataclass
import math

MAX_RULES = 64
MAX_RULES_PER_SOURCE = 8
MAX_TEXT = 256
MAX_INTEGER_BITS = 1024
OPERATORS = frozenset(("eq", "ne", "lt", "le", "gt", "ge"))
SCOPES = frozenset(
    ("supplied_value", "base_sample", "complete_small_inspection", "source_metadata")
)
METRICS = frozenset(
    (
        "value",
        "mean",
        "min",
        "max",
        "missing_fraction",
        "missing_count",
        "inspected",
        "length",
        "rows",
        "columns",
    )
)


def scalar(value):
    if type(value) is bool:
        return value
    if type(value) is int and value.bit_length() <= MAX_INTEGER_BITS:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if (
        type(value) is str
        and len(value) <= MAX_TEXT
        and len(value.encode("utf-8", "replace")) <= MAX_TEXT
        and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    ):
        return value
    raise ValueError("check values must be bounded finite scalars")


def tokens(value):
    if type(value) not in (list, tuple) or len(value) > 8:
        raise ValueError("check paths require at most eight literal tokens")
    for token in value:
        if type(token) is int and 0 <= token <= 65535:
            continue
        if type(token) is str and token and scalar(token) == token:
            continue
        raise ValueError("invalid check path token")
    return tuple(value)


def text(value, limit=128):
    if (
        type(value) is not str
        or not value
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid check identifier or name")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("invalid check text")
    return value


@dataclass(frozen=True, slots=True)
class Rule:
    id: str
    name: str
    source: str
    kind: str
    path: tuple
    op: str
    value: object
    severity: str = "warning"
    enabled: bool = True
    input: str = "json"
    metric: str | None = None
    scope: str | None = None
    selection_path: tuple = ()
    unit: str | None = None
    notify: tuple = ()


def parse_checks(section, *, destinations=()):
    if type(section) is not dict or section.keys() - {"enabled", "rules"}:
        raise ValueError("invalid checks-settings fields")
    enabled = section.get("enabled", True)
    rows = section.get("rules", [])
    if type(enabled) is not bool or type(rows) is not list or len(rows) > MAX_RULES:
        raise ValueError("invalid checks-settings limits")
    rules, ids, counts = [], set(), {}
    allowed = set(Rule.__dataclass_fields__)
    for row in rows:
        if type(row) is not dict or row.keys() - allowed:
            raise ValueError("invalid check fields")
        if not {"id", "source", "kind", "path", "op", "value"} <= row.keys():
            raise ValueError("missing required check fields")
        data = dict(row)
        data["id"] = text(data["id"])
        data["name"] = text(data.get("name", data["id"]))
        data["source"] = text(data["source"], 512)
        data["path"] = tokens(data["path"])
        data["selection_path"] = tokens(data.get("selection_path", []))
        data["value"] = scalar(data["value"])
        if any(
            type(data[key]) is not str
            for key in ("kind", "op", "input", "severity", "scope", "metric")
            if key in data
        ):
            raise ValueError("invalid check option type")
        if data["id"] in ids:
            raise ValueError("duplicate check ID")
        ids.add(data["id"])
        counts[data["source"]] = counts.get(data["source"], 0) + 1
        if counts[data["source"]] > MAX_RULES_PER_SOURCE:
            raise ValueError("too many checks for one source")
        if data["kind"] not in ("state", "event") or data["op"] not in OPERATORS:
            raise ValueError("invalid check kind or operator")
        if data["op"] not in ("eq", "ne") and type(data["value"]) not in (int, float):
            raise ValueError("threshold operators require numeric values")
        if data.get("severity", "warning") not in ("noteworthy", "warning", "critical"):
            raise ValueError("invalid check severity")
        if type(data.get("enabled", True)) is not bool:
            raise ValueError("invalid check enabled flag")
        data["enabled"] = enabled and data.get("enabled", True)
        input_kind = data.get("input", "json")
        if input_kind not in ("json", "observation"):
            raise ValueError("invalid check input")
        if input_kind == "observation":
            if (
                data["kind"] != "state"
                or data.get("metric") not in METRICS
                or data.get("scope") not in SCOPES
            ):
                raise ValueError(
                    "observation checks require state, metric and explicit scope"
                )
            metadata_metric = data["metric"] in ("length", "rows", "columns")
            if (
                metadata_metric != (data["scope"] == "source_metadata")
                or metadata_metric
                and data["path"]
            ):
                raise ValueError("incompatible observation metadata scope")
        elif any(key in data for key in ("metric", "scope")) or data["selection_path"]:
            raise ValueError("observation selectors require observation input")
        if data.get("unit") is not None:
            data["unit"] = text(data["unit"], 32)
        references = data.get("notify", [])
        if (
            type(references) not in (list, tuple)
            or len(references) > 2
            or any(
                type(name) is not str or name not in destinations for name in references
            )
            or len(set(references)) != len(references)
        ):
            raise ValueError(
                "notification destination references are not configured or exceed limits"
            )
        data["notify"] = tuple(references)
        rules.append(Rule(**data))
    return tuple(rules)
