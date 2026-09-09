"""Detached scalar selection, with no scans/conversions of arbitrary objects."""

from dataclasses import dataclass
from fractions import Fraction
import sys
import time

from .checks_config import scalar, MAX_INTEGER_BITS

MISSING = object()


@dataclass(frozen=True, slots=True)
class Evidence:
    value: object = None
    reason: str | None = None
    scope: str = "supplied_value"
    unit: str | None = None
    inspected: int | None = None
    not_inspected: int | None = None


class Budget:
    def __init__(self, units=4096, deadline=None):
        self.remaining = units
        self.deadline = deadline

    def spend(self, amount=1):
        self.remaining -= amount
        if self.deadline is not None and time.thread_time() >= self.deadline:
            self.remaining = -1
        if self.remaining < 0:
            raise ValueError("selection_budget")


def lookup(value, path, budget):
    for token in path:
        budget.spend()
        if type(value) is dict:
            # Reject sparse/huge dictionaries before iteration; no hashing or
            # equality callbacks on user-supplied custom keys.
            size = dict.__sizeof__(value)
            if sys.implementation.name != "cpython" or size > 16384:
                raise ValueError("mapping_storage_budget")
            budget.spend(max(1, size // 64))
            found = MISSING
            for index, (key, item) in enumerate(dict.items(value)):
                if index >= 32:
                    break
                if (
                    type(key) is type(token)
                    and type(key) in (str, int)
                    and key == token
                ):
                    found = item
                    break
            value = found
        elif type(value) in (list, tuple) and type(token) is int and token < len(value):
            value = value[token]
        else:
            return MISSING
    return value


def typed(value, budget):
    kind = lookup(value, ("type",), budget)
    if type(kind) is not str:
        raise ValueError("unsupported_typed_value")
    raw = lookup(value, ("value",), budget)
    if (
        kind == "integer"
        and type(raw) is str
        and len(raw) <= 310
        and raw.lstrip("-").isascii()
        and raw.lstrip("-").isdigit()
    ):
        return scalar(int(raw))
    if kind == "rational":
        num = lookup(value, ("numerator",), budget)
        den = lookup(value, ("denominator",), budget)
        if (
            type(num) is str
            and len(num) <= 310
            and type(den) is int
            and 0 < den <= 4096
        ):
            numerator = int(num)
            if numerator.bit_length() <= MAX_INTEGER_BITS:
                return Fraction(numerator, den)
        raise ValueError("invalid_numeric_value")
    if kind not in ("integer", "float", "string", "bool"):
        raise ValueError("invalid_numeric_value")
    if (
        type(raw)
        is not {"integer": int, "float": float, "string": str, "bool": bool}[kind]
    ):
        raise ValueError("inconsistent_scalar_type")
    if (
        lookup(value, ("truncated",), budget) is True
        or lookup(value, ("encoding_replaced",), budget) is True
    ):
        raise ValueError("truncated_value")
    return scalar(raw)


def document_scalar(source, path, budget):
    """Select typed numeric/bool evidence from the existing JSON display tree.

    Never reparse pretty_text/raw_text or reconstruct a container. Legacy text
    leaves normalize whitespace, so they cannot establish exact string checks.
    """
    version = lookup(source, ("version",), budget)
    if type(version) is not int or version != 1:
        raise ValueError("document_version")
    node = lookup(source, ("root",), budget)
    for depth in range(1, len(path) + 1):
        children = lookup(node, ("children",), budget)
        if (
            type(children) is not list
            or len(children) > 32
            or lookup(node, ("truncated",), budget) is True
        ):
            raise ValueError("document_path")
        match = MISSING
        for index in range(min(len(children), 32)):
            candidate = children[index]
            tokens = lookup(candidate, ("path",), budget)
            if (
                type(tokens) is not list
                or len(tokens) != depth
                or any(
                    type(p) not in (str, int) or type(p) is str and len(p) > 256
                    for p in tokens
                )
            ):
                continue
            if tuple(tokens) == path[:depth]:
                if match is not MISSING:
                    raise ValueError("ambiguous_document_path")
                match = candidate
        node = match
    kind = lookup(node, ("value_kind",), budget)
    if (
        type(kind) is not str
        or kind not in ("int", "float", "bool")
        or lookup(node, ("truncated",), budget) is not False
    ):
        raise ValueError("document_scalar_unavailable")
    value = lookup(node, ("full_value",), budget)
    if type(value) is not str or len(value) > 310:
        raise ValueError("document_scalar_size")
    if kind == "bool":
        if value not in ("True", "False"):
            raise ValueError("document_bool")
        return value == "True"
    return scalar(int(value) if kind == "int" else float(value))


def select(rule, source, budget):
    try:
        if rule.input == "json":
            marker = lookup(source, ("type",), budget) if rule.kind == "state" else None
            if type(marker) is str and marker == "plotsrv_observation":
                return Evidence(reason="observation_requires_explicit_scope")
            if type(marker) is str and marker == "plotsrv_json_document":
                return Evidence(
                    document_scalar(source, rule.path, budget), unit=rule.unit
                )
            value = lookup(source, rule.path, budget)
            if value is MISSING:
                return Evidence(reason="missing_or_uninspected_path")
            return Evidence(scalar(value), unit=rule.unit)
        kind = lookup(source, ("type",), budget)
        version = lookup(source, ("observation_version",), budget)
        recipe = lookup(source, ("recipe_version",), budget)
        if (
            type(kind) is not str
            or kind != "plotsrv_observation"
            or type(version) is not int
            or version != 1
            or type(recipe) is not int
            or recipe != 1
        ):
            return Evidence(reason="incompatible_observation")
        selection = lookup(source, ("provenance", "selection", "path"), budget)
        if (
            type(selection) is not list
            or len(selection) > 8
            or any(
                type(p) not in (str, int) or type(p) is str and len(p) > 256
                for p in selection
            )
            or tuple(selection) != rule.selection_path
        ):
            return Evidence(reason="incompatible_source_scope")
        if rule.scope == "source_metadata":
            if rule.unit is not None:
                return Evidence(reason="unit_mismatch")
            path = (
                ("metadata", "length")
                if rule.metric == "length"
                else ("metadata", "shape", 0 if rule.metric == "rows" else 1)
            )
            value = lookup(source, path, budget)
            if type(value) is not int or value < 0:
                return Evidence(reason="metadata_unavailable")
            return Evidence(scalar(value), scope=rule.scope)
        fields = lookup(source, ("fields",), budget)
        if type(fields) is not list or len(fields) > 32:
            return Evidence(reason="field_unavailable")
        match = None
        for field in fields:
            budget.spend()
            position = lookup(field, ("position",), budget)
            if type(position) is int:
                columns = lookup(source, ("metadata", "fields"), budget)
                if type(columns) is not list or len(columns) > 32:
                    continue
                name = None
                for column in columns:
                    column_position = lookup(column, ("position",), budget)
                    if type(column_position) is int and column_position == position:
                        name = typed(lookup(column, ("label",), budget), budget)
                        break
                path = (name,)
            else:
                path = lookup(field, ("path",), budget)
                if path is MISSING:
                    path = []
                if type(path) is not list or len(path) > 8:
                    continue
                path = tuple(typed(part, budget) for part in path)
            if path == rule.path:
                if match is not None:
                    return Evidence(reason="ambiguous_field")
                match = field
        if match is None:
            return Evidence(reason="field_unavailable")
        scope = lookup(match, ("scope",), budget)
        if type(scope) is not str or scope != rule.scope:
            return Evidence(reason="incompatible_coverage")
        paths = {
            "value": ("value",),
            "mean": ("numeric", "mean"),
            "min": ("numeric", "min"),
            "max": ("numeric", "max"),
            "missing_fraction": ("missingness", "fraction"),
            "missing_count": ("missingness", "missing"),
            "inspected": ("values_inspected",),
        }
        value = lookup(match, paths[rule.metric], budget)
        inspected = lookup(match, ("values_inspected",), budget)
        omitted = lookup(match, ("not_inspected",), budget)
        if (
            type(inspected) is not int
            or not 0 <= inspected <= 4096
            or type(omitted) is not int
            or not 0 <= omitted <= 4096
        ):
            return Evidence(reason="no_inspected_values")
        if inspected == 0 and rule.metric != "inspected":
            return Evidence(reason="no_inspected_values")
        unit = lookup(value, ("unit",), budget) if type(value) is dict else MISSING
        unit = None if unit is MISSING else scalar(unit)
        if unit != rule.unit:
            return Evidence(reason="unit_mismatch")
        value = typed(value, budget) if type(value) is dict else scalar(value)
        return Evidence(
            value, scope=scope, unit=unit, inspected=inspected, not_inspected=omitted
        )
    except (ValueError, KeyError, TypeError, OverflowError):
        return Evidence(
            reason=(
                "selection_budget"
                if budget.remaining < 0
                else "invalid_or_bounded_evidence"
            )
        )
