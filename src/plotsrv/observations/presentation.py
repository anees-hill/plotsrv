"""Small projections of already-published evidence for the shared explorer."""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math

from .history import compact

MAX_DISTRIBUTIONS = 8
MAX_EXAMPLES = 16
MAX_RECIPES = 8
SCOPE = {
    "supplied_value": "Supplied metric",
    "complete_small_inspection": "Small positional inspection",
    "base_sample": "Observed sample",
    "captured_structure": "Inspected structure",
}
COLUMNS = [
    "surface",
    "field",
    "evidence",
    "inspected",
    "not_inspected",
    "missing",
    "missing_fraction",
    "value",
    "observed_min",
    "observed_max",
    "observed_mean",
    "bucket",
    "count",
    "received_at",
]


def typed(value):
    if type(value) is not dict:
        return "Not inspected"
    kind = value.get("type")
    if kind == "null" or value.get("null") is True:
        return "Null"
    if kind == "omitted":
        return "Not inspected"
    if kind == "rational":
        return f"{value['numerator']} / {value['denominator']}"
    if kind == "bool":
        return "True" if value.get("value") else "False"
    if kind in ("integer", "float", "string", "nonfinite"):
        text = str(value.get("value", ""))
        if value.get("truncated") or value.get("encoding_replaced"):
            text += " (prefix)"
        if value.get("approximate"):
            text += " (approximate)"
        return text[:1100]
    if kind == "temporal":
        return f"{value.get('value', value.get('ticks', ''))} {value.get('unit', '')}".strip()
    return {
        "sequence": "Nested sequence",
        "mapping": "Nested mapping",
        "bytes": "Binary example",
    }.get(kind, "Unsupported value")


def number(value):
    if type(value) is not dict:
        return None
    try:
        if value.get("type") == "integer":
            return int(value["value"])
        if value.get("type") == "float" and math.isfinite(value["value"]):
            return value["value"]
        if value.get("type") == "rational":
            return Fraction(int(value["numerator"]), value["denominator"])
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None
    return None


def plot_number(value):
    result = number(value)
    if type(result) is int and abs(result) <= 2**53 - 1 or type(result) is float:
        return result
    return None  # Display exact large integers/rationals, never silently round a trend.


def field_key(field):
    identity = {key: field[key] for key in ("path", "position") if key in field}
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()[:20]


def field_name(field, metadata):
    if "position" in field:
        for column in metadata.get("fields", []):
            if column.get("position") == field["position"]:
                return typed(column.get("label", {}))[:256]
        return f"Column {field['position']}"
    path = field.get("path", [])
    return " / ".join(typed(part) for part in path)[:256] or "Value"


def _policy(document):
    return {
        key: document.get(key)
        for key in ("observation_version", "recipe_version", "source_type", "sampling")
    }


def compatibility(current, previous):
    if previous is None:
        return "No compatible prior observation is retained."
    if current.get("history_evidence_omitted") or previous.get(
        "history_evidence_omitted"
    ):
        return "Prior evidence was omitted to stay within the history budget."
    session = current.get("provenance", {}).get("publisher_session")
    if not session or session != previous.get("provenance", {}).get(
        "publisher_session"
    ):
        return "Publisher session changed or is unknown; comparisons start again."
    selection = current.get("provenance", {}).get("selection")
    if selection is None or selection != previous.get("provenance", {}).get(
        "selection"
    ):
        return (
            "Selected source scope changed or is unknown; comparisons are unavailable."
        )
    if _policy(current) != _policy(previous):
        return "Source or sampling policy changed; metric comparisons are unavailable."
    if current["captured_at_unix_s"] <= previous["captured_at_unix_s"]:
        return "Capture order is repeated or uncertain; metric comparisons are unavailable."
    return None


def _source_schema(document):
    metadata = document.get("metadata", {})
    return {
        key: metadata[key]
        for key in ("fields", "dtype_kind", "itemsize", "unit", "timezone")
        if key in metadata
    }


def _observed_types(document, field):
    # For containers without declared dtypes, changes describe captured types only.
    return [] if _source_schema(document) else sorted(field.get("types", {}))


def _schema(document):
    return _source_schema(document), [
        (
            field_key(f),
            f.get("scope"),
            (f.get("value") or {}).get("type"),
            (f.get("value") or {}).get("unit"),
            _observed_types(document, f),
        )
        for f in document.get("fields", [])
    ]


def exact_delta(after, before):
    a, b = number(after), number(before)
    if a is None or b is None or type(a) is not type(b):
        return None
    delta = a - b
    if type(delta) is float and not math.isfinite(delta):
        return None
    return str(delta)


def shape(document):
    metadata = document.get("metadata", {})
    dimensions = metadata.get("shape")
    if type(dimensions) is list:
        return " × ".join(
            typed(v) if type(v) is dict else str(v) if v is not None else "unknown"
            for v in dimensions
        )
    length = metadata.get("length")
    return str(length) + " items" if type(length) is int else "Not available cheaply"


def changes(current, previous):
    reason = compatibility(current, previous)
    if reason:
        return reason, []
    rows = []
    before_shape, after_shape = shape(previous), shape(current)
    if before_shape != after_shape:
        rows.append(
            (
                "Known shape/length",
                before_shape,
                after_shape,
                "Cheap source metadata; these are not processed-row totals.",
            )
        )
    if _schema(current) != _schema(previous):
        rows.append(
            (
                "Captured schema",
                "Prior captured fields",
                "Different captured fields or types",
                "This does not prove removal outside captured coverage.",
            )
        )
        return (
            "Captured schema or evidence scope changed; metric comparisons are unavailable.",
            rows,
        )
    old_fields = {field_key(f): f for f in previous["fields"]}
    for field in current["fields"]:
        old = old_fields.get(field_key(field))
        if old is None:
            continue
        name = field_name(field, current["metadata"])
        if field.get("scope") == "supplied_value":
            delta = exact_delta(field.get("value"), old.get("value"))
            if delta is not None and delta not in ("0", "0.0"):
                rows.append(
                    (
                        name,
                        typed(old["value"]),
                        typed(field["value"]),
                        "Supplied metric change: " + delta,
                    )
                )
        elif (field.get("positions_captured"), field.get("values_inspected")) == (
            old.get("positions_captured"),
            old.get("values_inspected"),
        ):
            a, b = field.get("numeric", {}).get("mean"), old.get("numeric", {}).get(
                "mean"
            )
            delta = exact_delta(a, b)
            if delta is not None and delta not in ("0", "0.0"):
                rows.append(
                    (
                        name + " · observed mean",
                        typed(b),
                        typed(a),
                        SCOPE.get(field["scope"], "Observed evidence")
                        + "; not a statistical drift test.",
                    )
                )
            am, bm = field.get("missingness", {}), old.get("missingness", {})
            if (
                am.get("denominator")
                and am.get("denominator") == bm.get("denominator")
                and am.get("missing") != bm.get("missing")
            ):
                rows.append(
                    (
                        name + " · observed missing",
                        str(bm["missing"]),
                        str(am["missing"]),
                        f"Within {am['denominator']} inspected values; not a whole-source estimate.",
                    )
                )
    return (
        "Changes within compatible captured evidence. Sampling can visit different positions; unchanged values do not establish an all-clear."
        if rows
        else "No changes found in the compatible metadata and metrics compared. This does not establish whole-object equality."
    ), rows[:16]


def _spec(view_id, name, caption, columns, *, filters, plot=None):
    plot = plot or {"type": "bar", "source": "table"}
    return dict(
        version=1,
        sourceId=view_id,
        name=name[:80],
        caption=caption[:256],
        presentation=dict(
            search="",
            filters=[dict(field=k, op="eq", value=v, valueTo="") for k, v in filters],
            sort=[],
            group="",
            columns=columns,
            hidden=[column for column in COLUMNS if column not in columns],
            mode="plot+data" if len(plot) > 2 else "table",
            plot=plot,
        ),
        requirements=dict(
            fields=[
                dict(name=k, type="number" if k.startswith("evidence_") else "text")
                for k, v in filters
            ],
            plotFields=[],
            plotSource="table",
            capability="observation-v1",
        ),
    )


def binding(summary, field):
    """Presentation fields bind to metric meaning, never merely its position."""
    schema = next(
        (
            column
            for column in summary["metadata"].get("fields", [])
            if "position" in field and column.get("position") == field["position"]
        ),
        None,
    )
    identity = {
        "field": field_key(field),
        "schema": schema,
        "source": summary["source_type"],
        "source_schema": {
            key: val for key, val in _source_schema(summary).items() if key != "fields"
        },
        "observed_types": _observed_types(summary, field),
        "selection": summary["provenance"].get("selection"),
        "recipe": summary["recipe_version"],
        "scope": field["scope"],
        "type": field.get("value", {}).get("type"),
        "unit": field.get("value", {}).get("unit"),
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()[:20]


def project(summary, entries=()):
    rows, distributions, scalar_columns = [], [], []
    metadata = summary["metadata"]
    names = [field_name(field, metadata) for field in summary["fields"]]
    for index, field in enumerate(summary["fields"]):
        key, name = field_key(field), names[index]
        if names.count(name) > 1:
            name = name[:230] + f" · field {index + 1}"
        bound_key = binding(summary, field)
        numeric, missing = field.get("numeric", {}), field.get("missingness", {})
        row = dict(
            surface="Fields",
            field=name,
            evidence=SCOPE.get(field["scope"], field["scope"]),
            inspected=field["values_inspected"],
            not_inspected=field["not_inspected"],
            missing=missing.get("missing"),
            missing_fraction=missing.get("fraction"),
            value=typed(field["value"]) if "value" in field else "",
            observed_min=typed(numeric["min"]) if "min" in numeric else "",
            observed_max=typed(numeric["max"]) if "max" in numeric else "",
            observed_mean=typed(numeric["mean"]) if "mean" in numeric else "",
        )
        rows.append(row)
        if len(distributions) < MAX_DISTRIBUTIONS:
            bins = numeric.get("histogram", [])
            categories = field.get("categories", {}).get("top", [])
            points = [
                (
                    f"{typed(b['lower'])} – {typed(b['upper'])}"
                    + (
                        " (inclusive)"
                        if b.get("upper_inclusive")
                        else " (upper exclusive)"
                    ),
                    b["count"],
                )
                for b in bins[:8]
            ]
            if not points:
                points = [(typed(b["value"]), b["count"]) for b in categories[:8]]
            if points and field.get("scope") != "supplied_value":
                metric = "evidence_" + bound_key
                distributions.append((metric, name))
                for label, count in points:
                    rows.append(
                        dict(
                            surface="Distribution:" + bound_key,
                            **{metric: 1},
                            field=name,
                            evidence=row["evidence"]
                            + " · retained finite values/categories",
                            bucket=label,
                            count=count,
                        )
                    )
        if (
            len(scalar_columns) < 4
            and field.get("scope") == "supplied_value"
            and plot_number(field.get("value")) is not None
        ):
            scalar_columns.append(("metric_" + bound_key, key, name))
    # Never bridge an incompatible observation boundary in an automatic trend.
    compatible = []
    anchor = compact(summary)
    for entry in reversed(entries):
        if (
            not compatible
            and entry["captured_at_unix_s"] == anchor["captured_at_unix_s"]
            and entry.get("provenance") == anchor.get("provenance")
        ):
            compatible.append(entry)
            continue
        if compatibility(anchor, entry) or _schema(anchor) != _schema(entry):
            break
        compatible.append(entry)
        anchor = entry
    for entry in reversed(compatible):
        values = {field_key(f): f for f in entry["fields"]}
        row = dict(
            surface="Scalar history",
            received_at=datetime.fromtimestamp(
                entry["received_at"], timezone.utc
            ).isoformat(),
            evidence="Supplied metrics · irregular server receipt times",
        )
        for column, key, name in scalar_columns:
            value = values.get(key, {}).get("value")
            row[column] = plot_number(value)
        if scalar_columns:
            rows.append(row)
    examples = []
    if summary["examples_enabled"]:
        # Reserve room for useful probes even when base examples are all null.
        probes = summary.get("exploratory_examples", [])
        probe_count = min(4, sum(len(g.get("samples", [g])) for g in probes))
        for field in summary["fields"]:
            for sample in field.get("examples", []):
                if len(examples) >= MAX_EXAMPLES - probe_count:
                    break
                examples.append(
                    (
                        field_name(field, metadata),
                        str(sample.get("position", "")),
                        typed(sample["value"]),
                        "Base example",
                    )
                )
        for group in probes:
            for sample in group.get("samples", [group]):
                if len(examples) >= MAX_EXAMPLES:
                    break
                examples.append(
                    (
                        f"Column {group['field']}" if "field" in group else "Value",
                        str(sample.get("position", "")),
                        typed(sample["value"]),
                        "Exploratory probe · excluded from statistics",
                    )
                )
    columns = (
        COLUMNS
        + [column for column, _, _ in scalar_columns]
        + [marker for marker, _ in distributions]
    )
    recipes = [
        _spec(
            summary["view_id"],
            "Field overview",
            "Captured fields and supplied metrics, with inspected and missing-value denominators.",
            [
                "field",
                "evidence",
                "value",
                "inspected",
                "not_inspected",
                "missing",
                "observed_min",
                "observed_max",
                "observed_mean",
            ],
            filters=[("surface", "Fields")],
        )
    ]
    if any(row.get("missing_fraction") is not None for row in rows):
        recipes.append(
            _spec(
                summary["view_id"],
                "Observed missingness",
                "Missing fraction among inspected values; uninspected values are excluded.",
                ["field", "evidence", "missing", "inspected", "missing_fraction"],
                filters=[("surface", "Fields")],
                plot=dict(
                    type="bar",
                    source="table",
                    categoryField="field",
                    valueField="missing_fraction",
                    aggregation="max",
                    yLabel="Observed missing fraction",
                ),
            )
        )
    for metric, name in distributions[:3]:
        recipes.append(
            _spec(
                summary["view_id"],
                "Distribution · " + name,
                "Counts within retained observed bins/categories, not whole-source frequencies.",
                ["field", "evidence", "bucket", "count"],
                filters=[(metric, "1")],
                plot=dict(
                    type="bar",
                    source="table",
                    categoryField="bucket",
                    valueField="count",
                    aggregation="sum",
                    sort="category-asc",
                    yLabel="Observed count",
                ),
            )
        )
    if len(compatible) >= 2:
        for column, key, name in scalar_columns[:3]:
            recipes.append(
                _spec(
                    summary["view_id"],
                    "Recent · " + name,
                    "Supplied values at irregular server receipt times. No interpolation, zero filling or processed-row total.",
                    ["received_at", "evidence", column],
                    filters=[("surface", "Scalar history")],
                    plot=dict(
                        type="scatter",
                        source="table",
                        xField="received_at",
                        yField=column,
                        xLabel="Server receipt time",
                        yLabel=name[:256],
                    ),
                )
            )
    for recipe in recipes:
        recipe["presentation"]["hidden"] = [
            c for c in columns if c not in recipe["presentation"]["columns"]
        ]
    labels = {column: column.replace("_", " ").capitalize() for column in COLUMNS}
    labels.update({column: name for column, _, name in scalar_columns})
    labels.update({marker: "Observed bins · " + name for marker, name in distributions})
    return dict(
        columns=columns,
        rows=rows,
        recipes=recipes[:MAX_RECIPES],
        labels=labels,
        examples=examples,
        distributions=len(distributions),
    )
