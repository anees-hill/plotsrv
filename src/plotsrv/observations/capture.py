"""Bounded synchronous capture. Only the resulting JSON bytes cross the boundary."""

from __future__ import annotations

import json
import math
import sys
import time

from .models import CaptureEnvelope, CaptureOptions, ObservationBudget


class _Limit(Exception):
    pass


def positions(length: int, count: int) -> list[int]:
    count = min(length, count)
    if count < 2:
        return [0] if count else []
    return [i * (length - 1) // (count - 1) for i in range(count)]


def spread_first(ordered: list[int]) -> list[int]:
    """Visit endpoints, then bisect remaining spans, even on an early exit.

    Only use on bounded position lists; never on the source itself.
    """
    if len(ordered) < 3:
        return ordered
    result = [ordered[0], ordered[-1]]
    spans = [(1, len(ordered) - 2)]
    for left, right in spans:
        mid = (left + right) // 2
        result.append(ordered[mid])
        if left < mid:
            spans.append((left, mid - 1))
        if mid < right:
            spans.append((mid + 1, right))
    return result


class Capture:
    def __init__(self, budget: ObservationBudget, options: CaptureOptions):
        self.b = budget
        self.options = options
        self.deadline = time.monotonic() + budget.capture_ms / 1000
        self.elements = 0
        self.placement_scan_allowance = 0
        self.nodes = 0
        self.value_bytes = 0
        # Conservative working/inspection allowance, distinct from encoded output.
        self.charged_bytes = 2048
        self.reasons: set[str] = set()
        self.active: set[int] = set()
        self.categories: set[str] = set()
        self.field_limits: tuple[int, int, int] | None = None

    def share_field(self, remaining: int) -> None:
        """Reserve an equal share of remaining effort for each selected field."""
        self.field_limits = (
            self.elements + (self.b.max_elements - self.elements) // remaining,
            self.nodes + (self.b.max_nodes - self.nodes) // remaining,
            self.charged_bytes
            + (self.b.max_capture_bytes - self.charged_bytes) // remaining,
        )

    def reason(self, code: str) -> None:
        if len(self.reasons) < 16:
            self.reasons.add(code)

    def charge(self, *, reads: int = 0, nodes: int = 0, size: int = 0) -> None:
        for failed, code in (
            (self.elements + reads > self.b.max_elements, "element_budget"),
            (self.nodes + nodes > self.b.max_nodes, "node_budget"),
            (
                self.charged_bytes + size > self.b.max_capture_bytes,
                "capture_byte_budget",
            ),
            (time.monotonic() >= self.deadline, "soft_deadline"),
        ):
            if failed:
                self.reason(code)
                raise _Limit(code)
        if self.field_limits is not None:
            for total, limit, code in zip(
                (self.elements + reads, self.nodes + nodes, self.charged_bytes + size),
                self.field_limits,
                ("field_element_budget", "field_node_budget", "field_byte_budget"),
            ):
                if total > limit:
                    self.reason(code)
                    raise _Limit(code)
        self.elements += reads
        self.nodes += nodes
        self.charged_bytes += size

    def omitted(self, reason: str) -> dict:
        self.charge(nodes=1, size=768)
        self.reason(reason)
        return {"type": "omitted", "reason": reason}

    def text(self, value: str, *, category: bool = True) -> dict:
        # Slice before encoding; a code point costs at most four UTF-8 bytes.
        cap = self.b.max_value_bytes
        count = min(len(value), cap)
        self.charge(size=count * 32 + 256)
        prefix = value[:count]
        replaced = any(0xD800 <= ord(char) <= 0xDFFF for char in prefix)
        encoded = prefix.encode("utf-8", errors="replace")[:cap]
        text = encoded.decode("utf-8", errors="ignore")
        size = len(text.encode("utf-8"))
        self.value_bytes += size
        if category:
            if (
                text not in self.categories
                and len(self.categories) >= self.b.max_categories
            ):
                return self.omitted("category_budget")
            self.categories.add(text)
        if replaced:
            self.reason("invalid_unicode_replaced")
        truncated = len(text) != len(value)
        if truncated:
            self.reason("value_truncated")
        return {
            "type": "string",
            "value": text,
            "truncated": truncated,
            "encoding_replaced": replaced,
        }

    def mapping_entries(self, value: dict):
        # len(dict) says nothing about deleted slots. On CPython __sizeof__ is
        # constant-time and accounts for the backing table. Charge its entire
        # possible scan before constructing/advancing an iterator, including
        # nested dictionaries and selected paths. Do not introspect other VMs.
        if sys.implementation.name != "cpython":
            self.reason("unsupported_mapping_storage")
            raise _Limit
        storage = dict.__sizeof__(value)
        if storage > self.b.max_capture_bytes - self.charged_bytes:
            self.reason("mapping_storage_budget")
            raise _Limit
        self.charge(size=storage)
        return iter(value.items())

    def value(self, value: object, depth: int = 0, *, category: bool = True) -> dict:
        self.charge(nodes=1, size=768)
        kind = type(value)
        if value is None:
            return {"type": "null"}
        if kind is bool:
            return {"type": "bool", "value": value}
        if kind is int:
            if value.bit_length() > min(256, (self.b.max_value_bytes - 1) * 3):
                return self.omitted("integer_too_large")
            return {
                "type": "integer",
                "value": str(value) if abs(value) > 2**53 - 1 else value,
            }
        if kind is float:
            if not math.isfinite(value):
                return {
                    "type": "nonfinite",
                    "value": (
                        "nan" if math.isnan(value) else "inf" if value > 0 else "-inf"
                    ),
                }
            return {"type": "float", "value": value}
        if kind is str:
            return self.text(value, category=category)
        if kind is bytes:
            # Binary contents are examples, never necessary for numeric summaries.
            result = {"type": "bytes", "length": len(value)}
            if self.options.include_examples:
                length = min(len(value), self.b.max_value_bytes // 2)
                self.charge(size=length * 4 + 128)
                result["hex"] = value[:length].hex()
                result["truncated"] = length < len(value)
                self.value_bytes += length
            return result
        pd = sys.modules.get("pandas")
        if pd is not None and (value is pd.NA or value is pd.NaT):
            return {"type": "null"}
        np = sys.modules.get("numpy")
        if np is not None:
            # Exact built-in NumPy scalar types only; never invoke object.item().
            if any(
                kind is getattr(np, name)
                for name in (
                    "int8",
                    "int16",
                    "int32",
                    "int64",
                    "uint8",
                    "uint16",
                    "uint32",
                    "uint64",
                    "float16",
                    "float32",
                    "float64",
                    "bool_",
                )
            ):
                return self.value(value.item(), depth)
        if kind is not dict and kind is not list and kind is not tuple:
            return self.omitted("unsupported_value")
        if depth >= self.b.max_depth:
            return self.omitted("depth_budget")
        if id(value) in self.active:
            return self.omitted("cycle")
        self.active.add(id(value))
        initial = len(value)
        result = {
            "type": "mapping" if kind is dict else "sequence",
            "length": initial,
            "sampling": (
                "bounded_insertion_order_fields"
                if kind is dict
                else "deterministic_distributed_positions"
            ),
            "items": [],
        }
        selected_keys = (
            set() if kind is dict and depth == 0 and self.options.fields else None
        )
        try:
            if kind is dict:
                if initial > self.b.max_fields:
                    self.reason("field_budget")
                entries = self.mapping_entries(value)
                for _ in range(min(initial, self.b.max_fields)):
                    self.charge(reads=1)
                    key, item = next(entries)
                    if type(key) is not str and type(key) is not int:
                        self.reason("unsupported_key")
                        continue
                    if (
                        self.options.fields
                        and depth == 0
                        and not any(
                            type(key) is type(k) and key == k
                            for k in self.options.fields
                        )
                    ):
                        continue
                    if selected_keys is not None:
                        selected_keys.add(key)
                    result["items"].append(
                        {
                            "key": self.value(key, depth + 1, category=False),
                            "value": self.value(item, depth + 1),
                        }
                    )
            else:
                self.charge(size=128 * min(initial, self.b.max_rows))
                for index in spread_first(positions(initial, self.b.max_rows)):
                    self.charge(reads=1)
                    result["items"].append(
                        {
                            "position": index,
                            "value": self.value(value[index], depth + 1),
                        }
                    )
                if initial > self.b.max_rows:
                    self.reason("row_budget")
        except _Limit:
            pass
        finally:
            self.active.remove(id(value))
            if kind is not dict:
                result["items"].sort(key=lambda item: item["position"])
            if selected_keys is not None and any(
                key not in selected_keys for key in self.options.fields
            ):
                self.reason("field_not_inspected_or_absent")
        if len(value) != initial:
            self.reason("concurrent_mutation")
            result["items"] = []
        return result

    def select_path(self, source: object) -> object:
        for key in self.options.path:
            if type(source) is dict:
                found = False
                entries = self.mapping_entries(source)
                for _ in range(min(len(source), self.b.max_fields)):
                    self.charge(reads=1)
                    candidate, value = next(entries)
                    if type(candidate) is type(key) and candidate == key:
                        source, found = value, True
                        break
                if not found:
                    self.reason("path_not_inspected_or_absent")
                    raise _Limit
            elif (
                (type(source) is list or type(source) is tuple)
                and type(key) is int
                and key < len(source)
            ):
                self.charge(reads=1)
                source = source[key]
            else:
                self.reason("unsupported_path")
                raise _Limit
        return source


def capture_detached(
    source: object,
    *,
    view_id: str = "observation",
    budget: ObservationBudget = ObservationBudget(),
    options: CaptureOptions = CaptureOptions(),
) -> CaptureEnvelope:
    """Internal evidence, not a publication payload. Fail closed without logging data.

    Call CaptureEngine.submit for process admission. Direct calls are useful for
    adapter tests; they do not enforce aggregate cadence or downstream capacity.
    """
    if type(budget) is not ObservationBudget or type(options) is not CaptureOptions:
        raise ValueError("invalid capture configuration")
    if (
        type(view_id) is not str
        or not 0 < len(view_id) <= 512
        or any(0xD800 <= ord(c) <= 0xDFFF for c in view_id)
    ):
        raise ValueError("invalid observation identity")
    c = Capture(budget, options)
    document = {
        "version": 1,
        "captured_at_unix_s": time.time(),
        "view_id": view_id,
        "source_type": "unsupported",
        "metadata": {},
        "examples_enabled": options.include_examples,
        "base_sample": [],
        "exploratory": [],
        "sampling": "deterministic_distributed_positions",
        "consistency": "best_effort",
    }
    try:
        source = c.select_path(source)
        from .adapters import capture_array, capture_pandas, capture_polars

        np, pd, pl = (sys.modules.get(name) for name in ("numpy", "pandas", "polars"))
        if np is not None and type(source) is np.ndarray:
            capture_array(c, source, document, np)
        elif pd is not None and type(source) is pd.DataFrame:
            capture_pandas(c, source, document, np, pd)
        elif pl is not None and type(source) is pl.DataFrame:
            capture_polars(c, source, document, pl)
        else:
            kind = type(source)
            if options.fields and kind is not dict:
                c.reason("unsupported_field_selection")
                raise _Limit
            if kind is dict:
                document["sampling"] = "bounded_insertion_order_fields"
            elif kind is not list and kind is not tuple:
                document["sampling"] = "single_value_or_unsupported"
            if kind is dict or kind is list or kind is tuple:
                document["metadata"] = {"length": len(source)}
            document["source_type"] = next(
                (
                    name
                    for cls, name in (
                        (dict, "dict"),
                        (list, "list"),
                        (tuple, "tuple"),
                        (int, "scalar"),
                        (float, "scalar"),
                        (bool, "scalar"),
                        (str, "scalar"),
                    )
                    if kind is cls
                ),
                "unsupported",
            )
            value = c.value(source)
            if document["source_type"] == "unsupported" and value["type"] != "omitted":
                document["source_type"] = "scalar"
            document["base_sample"].append(value)
    except _Limit:
        pass
    except Exception:
        # No exception text/type inspection, source repr or logging callbacks.
        c.reason("unsafe_or_changed_source")
        document["base_sample"] = []
        document["exploratory"] = []
    document["coverage"] = {
        "elements_read": c.elements - c.placement_scan_allowance,
        "element_units_charged": c.elements,
        "placement_scan_allowance": c.placement_scan_allowance,
        "nodes": c.nodes,
        "value_bytes": c.value_bytes,
        "charged_capture_bytes": c.charged_bytes,
        "exact": False,
    }
    document["reasons"] = sorted(c.reasons)
    encoded = json.dumps(
        document, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > budget.max_output_bytes:
        # The working representation was already structurally/byte bounded.
        document["base_sample"] = []
        document["exploratory"] = []
        document["metadata"] = {}
        document["reasons"] = ["output_byte_budget"]
        encoded = json.dumps(
            document, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    return CaptureEnvelope(encoded)
