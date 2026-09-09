"""Small summaries of detached evidence only; never accepts a pipeline object."""

from __future__ import annotations

import bisect
import json
import math

from .models import CaptureEnvelope, ObservationBudget

OBSERVATION_VERSION = 1
MAX_OBSERVATION_BYTES = 64 * 1024
MAX_SUMMARY_FIELDS = 32
MAX_SUMMARY_CATEGORIES = 16
# Eight source levels expand into typed item/value wrappers plus the envelope.
MAX_OBSERVATION_DEPTH = 32


def _number(value):
    if value.get("type") == "integer":
        return int(value["value"])
    if value.get("type") == "float":
        return value["value"]
    return None


def _numeric(value):
    if type(value) is int:
        return {
            "type": "integer",
            "value": str(value) if abs(value) > 2**53 - 1 else value,
        }
    return {"type": "float", "value": value}


def _ratio(numerator, denominator):
    if numerator % denominator == 0:
        return _numeric(numerator // denominator)
    divisor = math.gcd(numerator, denominator)
    return {
        "type": "rational",
        "numerator": str(numerator // divisor),
        "denominator": denominator // divisor,
    }


def _numeric_summary(numbers):
    ordered = sorted(numbers)
    count = len(ordered)
    low, high = ordered[0], ordered[-1]
    integers = all(type(n) is int for n in ordered)
    precise_float_input = all(type(n) is float or abs(n) <= 2**53 - 1 for n in ordered)
    result = {
        "count": count,
        "min": _numeric(low),
        "max": _numeric(high),
        "quantiles": {
            "method": "nearest_rank_on_observed_values",
            **{
                name: _numeric(ordered[max(0, math.ceil(count * p) - 1)])
                for name, p in (("p25", 0.25), ("p50", 0.5), ("p75", 0.75))
            },
        },
    }
    if integers:
        result["mean"] = _ratio(sum(ordered), count)
    elif precise_float_input:
        try:
            mean = math.fsum(n / count for n in ordered)
            if math.isfinite(mean):
                result["mean"] = {**_numeric(mean), "approximate": True}
        except (OverflowError, ValueError):
            pass
    if "mean" not in result:
        result["mean_unavailable"] = "numeric_precision_or_range"
    if low == high:
        result["histogram"] = [
            {
                "lower": _numeric(low),
                "upper": _numeric(high),
                "count": count,
                "upper_inclusive": True,
            }
        ]
    elif integers or precise_float_input:
        bins = min(8, count)
        counts = [0] * bins
        if integers:
            edges = [
                _ratio(low * bins + (high - low) * i, bins) for i in range(bins + 1)
            ]
            for number in ordered:
                counts[min(bins - 1, (number - low) * bins // (high - low))] += 1
        else:
            raw_edges = [
                (1 - i / bins) * low + (i / bins) * high for i in range(bins + 1)
            ]
            if not all(math.isfinite(edge) for edge in raw_edges):
                return result
            edges = [_numeric(edge) for edge in raw_edges]
            for number in ordered:
                counts[
                    min(bins - 1, max(0, bisect.bisect_right(raw_edges, number) - 1))
                ] += 1
        result["histogram"] = [
            {
                "lower": edges[i],
                "upper": edges[i + 1],
                "count": counts[i],
                "upper_inclusive": i == bins - 1,
            }
            for i in range(bins)
        ]
    return result


def _missing(value):
    return (
        value.get("type") == "null"
        or value.get("null") is True
        or (value.get("type") == "nonfinite" and value.get("value") == "nan")
    )


def _summarize(values, *, scope):
    missing = uninspected = nonfinite = 0
    numbers, categories = [], {}
    types = {}
    truncated = False
    for value in values:
        kind = value.get("type", "omitted")
        types[kind] = types.get(kind, 0) + 1
        if kind == "omitted":
            uninspected += 1
            continue
        missing += int(_missing(value))
        nonfinite += int(kind == "nonfinite")
        number = _number(value)
        if number is not None:
            numbers.append(number)
        if kind in ("string", "bool"):
            key = json.dumps(
                value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
            if key in categories:
                categories[key][1] += 1
            elif len(categories) < MAX_SUMMARY_CATEGORIES:
                categories[key] = [value, 1]
            else:
                truncated = True
            truncated |= bool(value.get("truncated") or value.get("encoding_replaced"))
    inspected = len(values) - uninspected
    result = {
        "scope": scope,
        "positions_captured": len(values),
        "values_inspected": inspected,
        "not_inspected": uninspected,
        "types": types,
        "missingness": {
            "missing": missing,
            "denominator": inspected,
            "fraction": missing / inspected if inspected else None,
        },
        "nonfinite": nonfinite,
    }
    if numbers:
        result["numeric"] = _numeric_summary(numbers)
        result["numeric"]["distinct_values_observed"] = len(set(numbers))
    if categories:
        result["categories"] = {
            "distinct_typed_values_retained": len(categories),
            "complete_for_captured_values": not truncated and not uninspected,
            "prefixes_or_capped": truncated,
            "top": [
                {"value": value, "count": count}
                for value, count in sorted(
                    categories.values(), key=lambda pair: -pair[1]
                )
            ],
        }
    return result


def _scope(samples, length):
    # Full positional coverage is a small inspection, not an atomic snapshot.
    if (
        type(length) is int
        and len(samples) == length
        and all(s["position"] == i for i, s in enumerate(samples))
    ):
        return "complete_small_inspection"
    return "base_sample"


def _precision_safe(value):
    if type(value) is int and abs(value) > 2**53 - 1:
        return _numeric(value)
    if type(value) is dict:
        return {k: _precision_safe(v) for k, v in value.items()}
    if type(value) is list:
        return [_precision_safe(v) for v in value]
    return value


def build_summary(
    envelope: CaptureEnvelope,
    *,
    budget: ObservationBudget,
    diagnostics: dict | None = None,
    publisher_session: str | None = None,
) -> dict:
    if (
        type(envelope) is not CaptureEnvelope
        or len(envelope.payload) > budget.max_output_bytes
    ):
        raise ValueError("invalid detached observation")
    document = envelope.document()
    if document.get("version") != 1:
        raise ValueError("unsupported capture version")
    result = {
        "type": "plotsrv_observation",
        "observation_version": OBSERVATION_VERSION,
        "recipe_version": 1,
        "view_id": document["view_id"],
        "source_type": document["source_type"],
        "captured_at_unix_s": document["captured_at_unix_s"],
        "provenance": {
            "origin": "python_publisher",
            "consistency": document["consistency"],
            "selection": document.get("selection"),
        },
        "sampling": {
            "method": document["sampling"],
            "unbiased_random": False,
            "limits": {
                name: getattr(budget, name)
                for name in (
                    "max_rows",
                    "max_fields",
                    "max_elements",
                    "max_nodes",
                    "max_depth",
                    "max_value_bytes",
                    "max_categories",
                    "max_capture_bytes",
                    "exploratory_rows",
                )
            },
        },
        "coverage": document["coverage"],
        "metadata": document["metadata"],
        "fields": [],
        "reasons": document["reasons"],
        "examples_enabled": document["examples_enabled"],
        "delivery": diagnostics or {},
    }
    if publisher_session is not None:
        result["provenance"]["publisher_session"] = publisher_session
    fields = result["fields"]

    def field(values, *, path=None, position=None, scope="base_sample", examples=None):
        if len(fields) >= MAX_SUMMARY_FIELDS:
            if "summary_field_budget" not in result["reasons"]:
                result["reasons"].append("summary_field_budget")
            return
        entry = _summarize(values, scope=scope)
        if path is not None:
            entry["path"] = path
        if position is not None:
            entry["position"] = position
        if (
            scope == "supplied_value"
            and values
            and values[0].get("type")
            in ("null", "bool", "integer", "float", "nonfinite", "string", "temporal")
        ):
            entry["value"] = values[0]
        if document["examples_enabled"] and examples:
            entry["examples"] = examples
        fields.append(entry)

    def nested(value, path):
        # A recursive local closure would form a reference cycle retaining the
        # decoded capture until cyclic GC. Keep release independent of GC policy.
        pending = [(value, path, 0)]
        while pending:
            value, path, depth = pending.pop()
            if len(fields) >= MAX_SUMMARY_FIELDS or depth > 8:
                if "summary_field_budget" not in result["reasons"]:
                    result["reasons"].append("summary_field_budget")
                break
            if value.get("type") == "mapping":
                if not value["items"]:
                    field([value], path=path, scope="captured_structure")
                pending.extend(
                    (item["value"], [*path, item["key"]], depth + 1)
                    for item in reversed(value["items"])
                )
            elif value.get("type") == "sequence":
                samples = value["items"]
                field(
                    [s["value"] for s in samples],
                    path=path,
                    scope=_scope(samples, value["length"]),
                    examples=samples,
                )
            else:
                field([value], path=path, scope="supplied_value")

    base = document["base_sample"]
    if document["source_type"] == "pandas.DataFrame":
        height = document["metadata"].get("shape", [None])[0]
        for column in base:
            samples = column["samples"]
            field(
                [s["value"] for s in samples],
                position=column["field"],
                scope=_scope(samples, height),
                examples=samples,
            )
    elif document["source_type"] == "numpy.ndarray":
        shape = document["metadata"].get("shape", [])
        length = math.prod(shape)
        field([s["value"] for s in base], scope=_scope(base, length), examples=base)
    elif base:
        nested(base[0], [])
    probes = document["exploratory"]
    probe_values = (
        [sample["value"] for column in probes for sample in column["samples"]]
        if document["source_type"] == "pandas.DataFrame"
        else [s["value"] for s in probes]
    )
    result["exploration"] = {
        "positions_captured": len(probe_values),
        "useful_values": sum(
            not _missing(v) and v.get("type") not in ("omitted", "nonfinite")
            for v in probe_values
        ),
        "included_in_base_statistics": False,
    }
    if document["examples_enabled"] and probes:
        result["exploratory_examples"] = probes
    result = _precision_safe(result)
    limit = min(MAX_OBSERVATION_BYTES, budget.max_output_bytes)
    encoded = encode_summary(result)
    if len(encoded) > limit:
        # The input and summary construction already have fixed structural caps.
        # Drop examples first; never return private base evidence as a fallback.
        for entry in result["fields"]:
            entry.pop("examples", None)
        result.pop("exploratory_examples", None)
        result["reasons"].append("summary_output_budget")
        while result["fields"] and len(encode_summary(result)) > limit:
            del result["fields"][len(result["fields"]) // 2 :]
        if len(encode_summary(result)) > limit:
            result["metadata"] = {}
    if len(encode_summary(result)) > limit:
        raise ValueError("observation output budget")
    return result


def encode_summary(document: dict) -> bytes:
    return json.dumps(
        document, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def validate_summary(document: object, *, view_id: str) -> dict:
    """Server boundary: reject private capture envelopes and oversized trees."""
    if type(document) is not dict or document.get("type") != "plotsrv_observation":
        raise ValueError("invalid observation")
    if (
        type(document.get("observation_version")) is not int
        or document["observation_version"] != OBSERVATION_VERSION
        or type(document.get("recipe_version")) is not int
        or document.get("recipe_version") != 1
    ):
        raise ValueError("unsupported observation version")
    required = {
        "type",
        "observation_version",
        "recipe_version",
        "view_id",
        "source_type",
        "captured_at_unix_s",
        "provenance",
        "sampling",
        "coverage",
        "metadata",
        "fields",
        "reasons",
        "examples_enabled",
        "delivery",
        "exploration",
    }
    if not required <= document.keys() or document.keys() - required - {
        "exploratory_examples"
    }:
        raise ValueError("invalid observation fields")
    if document["view_id"] != view_id or type(document["examples_enabled"]) is not bool:
        raise ValueError("invalid observation identity")
    if (
        type(document["fields"]) is not list
        or len(document["fields"]) > MAX_SUMMARY_FIELDS
    ):
        raise ValueError("invalid observation fields")
    for name in (
        "provenance",
        "sampling",
        "coverage",
        "metadata",
        "delivery",
        "exploration",
    ):
        if type(document[name]) is not dict:
            raise ValueError("invalid observation section")
    if type(document["source_type"]) is not str or len(document["source_type"]) > 64:
        raise ValueError("invalid observation source")
    if type(document["captured_at_unix_s"]) not in (int, float):
        raise ValueError("invalid observation timestamp")
    if type(document["reasons"]) is not list or any(
        type(r) is not str for r in document["reasons"]
    ):
        raise ValueError("invalid observation reasons")
    for entry in document["fields"]:
        if type(entry) is not dict or entry.get("scope") not in (
            "supplied_value",
            "captured_structure",
            "base_sample",
            "complete_small_inspection",
        ):
            raise ValueError("invalid observation evidence scope")
        for name in (
            "positions_captured",
            "values_inspected",
            "not_inspected",
            "nonfinite",
        ):
            if type(entry.get(name)) is not int or not 0 <= entry[name] <= 4096:
                raise ValueError("invalid observation count")
        if (
            entry["values_inspected"] + entry["not_inspected"]
            != entry["positions_captured"]
        ):
            raise ValueError("inconsistent observation counts")
        if (
            type(entry.get("types")) is not dict
            or type(entry.get("missingness")) is not dict
        ):
            raise ValueError("invalid observation statistics")
    nodes = 0
    stack = [(document, 0)]
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > 16384 or depth > MAX_OBSERVATION_DEPTH:
            raise ValueError("observation structure budget")
        if type(value) is dict:
            if len(value) > 128 or any(
                type(k) is not str or len(k) > 128 for k in value
            ):
                raise ValueError("invalid observation mapping")
            if not document["examples_enabled"] and (
                "examples" in value or "exploratory_examples" in value
            ):
                raise ValueError("observation examples disabled")
            stack.extend((v, depth + 1) for v in value.values())
        elif type(value) is list:
            if len(value) > 256:
                raise ValueError("observation list budget")
            stack.extend((v, depth + 1) for v in value)
        elif type(value) is str:
            if len(value) > 2048 or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
                raise ValueError("observation text budget")
        elif type(value) is float:
            if not math.isfinite(value):
                raise ValueError("nonfinite observation number")
        elif type(value) is int:
            if abs(value) > 2**53 - 1:
                raise ValueError("unencoded observation integer")
        elif value is not None and type(value) is not bool:
            raise ValueError("invalid observation value")
    if len(encode_summary(document)) > MAX_OBSERVATION_BYTES:
        raise ValueError("observation output budget")
    return document
