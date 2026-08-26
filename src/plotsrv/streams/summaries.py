"""Exact, bounded aggregates for compacted stream observations.

These objects are deliberately separate from the stream wire models.  They
describe derived windows and never stand in for a source record.  Their merge
operations use exact numeric rationals and deterministic bounded category
selection, so changing valid incremental grouping does not change the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
import json
import math
from typing import Any

from .models import StreamRecord


Scalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class SummaryLimits:
    """Fixed resource bounds for one derived summary window."""

    max_fields: int
    max_categories_per_field: int
    max_category_value_bytes: int

    def __post_init__(self) -> None:
        if self.max_fields < 1:
            raise ValueError("max_summary_fields must be at least one")
        if self.max_categories_per_field < 1:
            raise ValueError("max_categorical_values must be at least one")
        if self.max_category_value_bytes < 1:
            raise ValueError("max_categorical_value_bytes must be at least one")


@dataclass(slots=True)
class NumericSummary:
    """Exact sufficient statistics for finite JSON numeric field values."""

    count: int = 0
    total: Fraction = Fraction(0)
    minimum: Fraction | None = None
    maximum: Fraction | None = None
    first: Fraction | None = None
    last: Fraction | None = None
    minimum_sequence: int | None = None
    maximum_sequence: int | None = None
    first_sequence: int | None = None
    last_sequence: int | None = None

    def add(self, value: int | float, *, browser_sequence: int) -> None:
        exact = _exact_number(value)
        self.count += 1
        self.total += exact
        if self.minimum is None or (exact, browser_sequence) < (
            self.minimum,
            self.minimum_sequence,
        ):
            self.minimum = exact
            self.minimum_sequence = browser_sequence
        if self.maximum is None or (exact, -browser_sequence) > (
            self.maximum,
            -self.maximum_sequence,
        ):
            self.maximum = exact
            self.maximum_sequence = browser_sequence
        if self.first_sequence is None or browser_sequence < self.first_sequence:
            self.first = exact
            self.first_sequence = browser_sequence
        if self.last_sequence is None or browser_sequence > self.last_sequence:
            self.last = exact
            self.last_sequence = browser_sequence

    @property
    def mean(self) -> Fraction | None:
        """The exact mean of the included finite numeric values, if any."""
        return self.total / self.count if self.count else None

    @classmethod
    def merged(cls, left: NumericSummary, right: NumericSummary) -> NumericSummary:
        """Merge two aggregates without changing their exact statistics."""
        if left.count == 0:
            return right.copy()
        if right.count == 0:
            return left.copy()

        out = cls(count=left.count + right.count, total=left.total + right.total)
        out.minimum, out.minimum_sequence = _select_minimum(
            left.minimum,
            left.minimum_sequence,
            right.minimum,
            right.minimum_sequence,
        )
        out.maximum, out.maximum_sequence = _select_maximum(
            left.maximum,
            left.maximum_sequence,
            right.maximum,
            right.maximum_sequence,
        )
        out.first, out.first_sequence = _select_first(
            left.first,
            left.first_sequence,
            right.first,
            right.first_sequence,
        )
        out.last, out.last_sequence = _select_last(
            left.last,
            left.last_sequence,
            right.last,
            right.last_sequence,
        )
        return out

    def copy(self) -> NumericSummary:
        return NumericSummary(
            count=self.count,
            total=self.total,
            minimum=self.minimum,
            maximum=self.maximum,
            first=self.first,
            last=self.last,
            minimum_sequence=self.minimum_sequence,
            maximum_sequence=self.maximum_sequence,
            first_sequence=self.first_sequence,
            last_sequence=self.last_sequence,
        )


@dataclass(slots=True)
class CategoricalSummary:
    """Bounded exact counts for deterministically selected scalar values.

    Keys are canonical JSON scalar encodings.  Retaining the lexicographically
    lowest keys is merge-safe: a value omitted by a child because that child
    already had ``N`` lower keys cannot become one of the global lowest ``N``
    keys.  This lets selected counts remain exact while all other observations
    are explicitly represented by ``untracked_count``.
    """

    total_count: int = 0
    tracked_counts: dict[str, int] = field(default_factory=dict)
    untracked_count: int = 0

    def add(self, value: Scalar, *, limits: SummaryLimits) -> None:
        self.total_count += 1
        key = _canonical_scalar(value)
        if len(key.encode("utf-8")) > limits.max_category_value_bytes:
            self.untracked_count += 1
            return

        if key in self.tracked_counts:
            self.tracked_counts[key] += 1
            return

        selected = sorted((*self.tracked_counts, key))[ : limits.max_categories_per_field]
        if key not in selected:
            self.untracked_count += 1
            return

        discarded = set(self.tracked_counts).difference(selected)
        for discarded_key in discarded:
            self.untracked_count += self.tracked_counts.pop(discarded_key)
        self.tracked_counts[key] = 1

    @classmethod
    def merged(
        cls,
        left: CategoricalSummary,
        right: CategoricalSummary,
        *,
        limits: SummaryLimits,
    ) -> CategoricalSummary:
        total_count = left.total_count + right.total_count
        candidate_keys = set(left.tracked_counts).union(right.tracked_counts)
        selected = sorted(candidate_keys)[: limits.max_categories_per_field]
        tracked = {
            key: left.tracked_counts.get(key, 0) + right.tracked_counts.get(key, 0)
            for key in selected
        }
        return cls(
            total_count=total_count,
            tracked_counts=tracked,
            untracked_count=total_count - sum(tracked.values()),
        )

    def copy(self) -> CategoricalSummary:
        return CategoricalSummary(
            total_count=self.total_count,
            tracked_counts=dict(self.tracked_counts),
            untracked_count=self.untracked_count,
        )

    def rebounded(self, *, limits: SummaryLimits) -> CategoricalSummary:
        """Prune already-retained keys when live configuration becomes tighter."""
        eligible = (
            key
            for key in self.tracked_counts
            if len(key.encode("utf-8")) <= limits.max_category_value_bytes
        )
        selected = sorted(eligible)[: limits.max_categories_per_field]
        tracked = {key: self.tracked_counts[key] for key in selected}
        return CategoricalSummary(
            total_count=self.total_count,
            tracked_counts=tracked,
            untracked_count=self.total_count - sum(tracked.values()),
        )


@dataclass(slots=True)
class FieldSummary:
    """Per-field derived state without semantic processing of free text."""

    observed_count: int = 0
    numeric: NumericSummary | None = None
    categorical: CategoricalSummary | None = None
    non_scalar_count: int = 0

    def add(self, value: Any, *, browser_sequence: int, limits: SummaryLimits) -> None:
        self.observed_count += 1
        value_type = type(value)
        if value_type in (int, float):
            if self.numeric is None:
                self.numeric = NumericSummary()
            self.numeric.add(value, browser_sequence=browser_sequence)
            return
        if value is None or value_type in (str, bool):
            if self.categorical is None:
                self.categorical = CategoricalSummary()
            # Strings are opaque scalar keys only: no tokenisation, language
            # inference, or other semantic summarisation is performed.
            self.categorical.add(value, limits=limits)
            return
        self.non_scalar_count += 1

    @classmethod
    def merged(
        cls,
        left: FieldSummary | None,
        right: FieldSummary | None,
        *,
        limits: SummaryLimits,
    ) -> FieldSummary:
        if left is None:
            assert right is not None
            return right.copy()
        if right is None:
            return left.copy()
        return cls(
            observed_count=left.observed_count + right.observed_count,
            numeric=_merged_numeric(left.numeric, right.numeric),
            categorical=_merged_categorical(
                left.categorical, right.categorical, limits=limits
            ),
            non_scalar_count=left.non_scalar_count + right.non_scalar_count,
        )

    def copy(self) -> FieldSummary:
        return FieldSummary(
            observed_count=self.observed_count,
            numeric=None if self.numeric is None else self.numeric.copy(),
            categorical=(
                None if self.categorical is None else self.categorical.copy()
            ),
            non_scalar_count=self.non_scalar_count,
        )

    def rebounded(self, *, limits: SummaryLimits) -> FieldSummary:
        return FieldSummary(
            observed_count=self.observed_count,
            numeric=None if self.numeric is None else self.numeric.copy(),
            categorical=(
                None
                if self.categorical is None
                else self.categorical.rebounded(limits=limits)
            ),
            non_scalar_count=self.non_scalar_count,
        )


@dataclass(slots=True)
class SummaryWindow:
    """One visibly derived aggregate over a fixed or cumulative time range."""

    observed_from: datetime
    observed_until: datetime
    resolution_s: int | None
    record_count: int = 0
    record_bytes: int = 0
    first_browser_sequence: int | None = None
    last_browser_sequence: int | None = None
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    field_observation_count: int = 0
    untracked_field_observations: int = 0
    fields: dict[str, FieldSummary] = field(default_factory=dict)

    @property
    def schema_fields(self) -> tuple[str, ...]:
        """Bounded derived schema; never a source-record payload."""
        return tuple(sorted(self.fields))

    @property
    def is_cumulative(self) -> bool:
        """Whether this is the one oldest aggregate rather than a fixed bin."""
        return self.resolution_s is None

    def add_record(self, record: StreamRecord, *, limits: SummaryLimits) -> None:
        self.record_count += 1
        self.record_bytes += record.encoded_bytes
        self.field_observation_count += len(record.data)
        self.first_browser_sequence = _minimum_optional_int(
            self.first_browser_sequence, record.browser_sequence
        )
        self.last_browser_sequence = _maximum_optional_int(
            self.last_browser_sequence, record.browser_sequence
        )
        self.first_observed_at = _minimum_optional_datetime(
            self.first_observed_at, record.observed_at
        )
        self.last_observed_at = _maximum_optional_datetime(
            self.last_observed_at, record.observed_at
        )
        for field_name, value in record.data.items():
            self._add_field(
                field_name,
                value,
                browser_sequence=record.browser_sequence,
                limits=limits,
            )

    def _add_field(
        self,
        field_name: str,
        value: Any,
        *,
        browser_sequence: int,
        limits: SummaryLimits,
    ) -> None:
        summary = self.fields.get(field_name)
        if summary is None:
            selected = sorted((*self.fields, field_name))[: limits.max_fields]
            if field_name not in selected:
                self.untracked_field_observations += 1
                return
            for discarded_name in set(self.fields).difference(selected):
                discarded = self.fields.pop(discarded_name)
                self.untracked_field_observations += discarded.observed_count
            summary = FieldSummary()
            self.fields[field_name] = summary
        summary.add(value, browser_sequence=browser_sequence, limits=limits)

    @classmethod
    def merged(
        cls,
        left: SummaryWindow,
        right: SummaryWindow,
        *,
        limits: SummaryLimits,
        observed_from: datetime | None = None,
        observed_until: datetime | None = None,
        resolution_s: int | None = None,
    ) -> SummaryWindow:
        """Return the associative derived merge of two compatible windows."""
        candidate_fields = set(left.fields).union(right.fields)
        selected_fields = sorted(candidate_fields)[: limits.max_fields]
        fields = {
            field_name: FieldSummary.merged(
                left.fields.get(field_name), right.fields.get(field_name), limits=limits
            )
            for field_name in selected_fields
        }
        field_observation_count = (
            left.field_observation_count + right.field_observation_count
        )
        return cls(
            observed_from=(
                observed_from
                if observed_from is not None
                else min(left.observed_from, right.observed_from)
            ),
            observed_until=(
                observed_until
                if observed_until is not None
                else max(left.observed_until, right.observed_until)
            ),
            resolution_s=resolution_s,
            record_count=left.record_count + right.record_count,
            record_bytes=left.record_bytes + right.record_bytes,
            first_browser_sequence=_minimum_optional_int(
                left.first_browser_sequence, right.first_browser_sequence
            ),
            last_browser_sequence=_maximum_optional_int(
                left.last_browser_sequence, right.last_browser_sequence
            ),
            first_observed_at=_minimum_optional_datetime(
                left.first_observed_at, right.first_observed_at
            ),
            last_observed_at=_maximum_optional_datetime(
                left.last_observed_at, right.last_observed_at
            ),
            field_observation_count=field_observation_count,
            untracked_field_observations=(
                field_observation_count
                - sum(summary.observed_count for summary in fields.values())
            ),
            fields=fields,
        )

    def rebounded(self, *, limits: SummaryLimits) -> SummaryWindow:
        """Return this derived window constrained by a new, smaller policy."""
        selected_fields = sorted(self.fields)[: limits.max_fields]
        fields = {
            field_name: self.fields[field_name].rebounded(limits=limits)
            for field_name in selected_fields
        }
        return SummaryWindow(
            observed_from=self.observed_from,
            observed_until=self.observed_until,
            resolution_s=self.resolution_s,
            record_count=self.record_count,
            record_bytes=self.record_bytes,
            first_browser_sequence=self.first_browser_sequence,
            last_browser_sequence=self.last_browser_sequence,
            first_observed_at=self.first_observed_at,
            last_observed_at=self.last_observed_at,
            field_observation_count=self.field_observation_count,
            untracked_field_observations=(
                self.field_observation_count
                - sum(summary.observed_count for summary in fields.values())
            ),
            fields=fields,
        )

    def as_browser_dict(self, *, tier: str, limits: SummaryLimits) -> dict[str, Any]:
        """Return an explicitly derived, JSON-safe browser representation.

        This intentionally has no ``data`` member and no raw-row shape.  The
        browser receives aggregate boundaries, resolution, counts, and every
        truncation fact needed to distinguish this object from an event.
        """
        return {
            "object_type": "derived_stream_summary_window",
            "derived": True,
            "tier": tier,
            "observation_window": {
                "from": self.observed_from.isoformat(),
                "until": self.observed_until.isoformat(),
            },
            "resolution": (
                {"kind": "cumulative"}
                if self.resolution_s is None
                else {"kind": "fixed_seconds", "seconds": self.resolution_s}
            ),
            "record_count": str(self.record_count),
            "record_bytes": str(self.record_bytes),
            "first_browser_sequence": (
                None
                if self.first_browser_sequence is None
                else str(self.first_browser_sequence)
            ),
            "last_browser_sequence": (
                None
                if self.last_browser_sequence is None
                else str(self.last_browser_sequence)
            ),
            "field_observation_count": str(self.field_observation_count),
            "truncation": {
                "max_fields": limits.max_fields,
                "untracked_field_observations": str(
                    self.untracked_field_observations
                ),
            },
            "fields": [
                _field_browser_dict(
                    field_name,
                    summary,
                    max_categories=limits.max_categories_per_field,
                )
                for field_name, summary in sorted(self.fields.items())
            ],
        }


def _exact_number(value: int | float) -> Fraction:
    if type(value) is int:
        return Fraction(value)
    if not math.isfinite(value):
        raise ValueError("numeric summaries require finite values")
    return Fraction.from_float(value)


def _canonical_scalar(value: Scalar) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _merged_numeric(
    left: NumericSummary | None, right: NumericSummary | None
) -> NumericSummary | None:
    if left is None:
        return None if right is None else right.copy()
    if right is None:
        return left.copy()
    return NumericSummary.merged(left, right)


def _merged_categorical(
    left: CategoricalSummary | None,
    right: CategoricalSummary | None,
    *,
    limits: SummaryLimits,
) -> CategoricalSummary | None:
    if left is None:
        return None if right is None else right.copy()
    if right is None:
        return left.copy()
    return CategoricalSummary.merged(left, right, limits=limits)


def _exact_fraction_dict(value: Fraction | None) -> dict[str, str] | None:
    if value is None:
        return None
    # JSON number parsers in browsers lose integer precision above 2**53.
    # Decimal strings preserve the exact rational components for presentation.
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def _field_browser_dict(
    field_name: str, summary: FieldSummary, *, max_categories: int
) -> dict[str, Any]:
    numeric = summary.numeric
    categorical = summary.categorical
    return {
        "field": field_name,
        "observed_count": str(summary.observed_count),
        "numeric": (
            None
            if numeric is None
            else {
                "included_finite_count": str(numeric.count),
                "sum": _exact_fraction_dict(numeric.total),
                "mean": _exact_fraction_dict(numeric.mean),
                "minimum": _exact_fraction_dict(numeric.minimum),
                "maximum": _exact_fraction_dict(numeric.maximum),
                "first": _exact_fraction_dict(numeric.first),
                "last": _exact_fraction_dict(numeric.last),
            }
        ),
        "categorical": (
            None
            if categorical is None
            else {
                "observed_scalar_count": str(categorical.total_count),
                "max_exact_values": max_categories,
                "tracked_values": [
                    {"value_json": value_json, "count": str(count)}
                    for value_json, count in sorted(categorical.tracked_counts.items())
                ],
                "untracked_observations": str(categorical.untracked_count),
                "exact_per_value_counts_complete": (
                    categorical.untracked_count == 0
                ),
            }
        ),
        "non_scalar_observations": str(summary.non_scalar_count),
    }


def _select_minimum(
    left_value: Fraction | None,
    left_sequence: int | None,
    right_value: Fraction | None,
    right_sequence: int | None,
) -> tuple[Fraction, int]:
    assert left_value is not None and left_sequence is not None
    assert right_value is not None and right_sequence is not None
    return (
        (left_value, left_sequence)
        if (left_value, left_sequence) <= (right_value, right_sequence)
        else (right_value, right_sequence)
    )


def _select_maximum(
    left_value: Fraction | None,
    left_sequence: int | None,
    right_value: Fraction | None,
    right_sequence: int | None,
) -> tuple[Fraction, int]:
    assert left_value is not None and left_sequence is not None
    assert right_value is not None and right_sequence is not None
    return (
        (left_value, left_sequence)
        if (left_value, -left_sequence) >= (right_value, -right_sequence)
        else (right_value, right_sequence)
    )


def _select_first(
    left_value: Fraction | None,
    left_sequence: int | None,
    right_value: Fraction | None,
    right_sequence: int | None,
) -> tuple[Fraction, int]:
    assert left_value is not None and left_sequence is not None
    assert right_value is not None and right_sequence is not None
    return (
        (left_value, left_sequence)
        if left_sequence <= right_sequence
        else (right_value, right_sequence)
    )


def _select_last(
    left_value: Fraction | None,
    left_sequence: int | None,
    right_value: Fraction | None,
    right_sequence: int | None,
) -> tuple[Fraction, int]:
    assert left_value is not None and left_sequence is not None
    assert right_value is not None and right_sequence is not None
    return (
        (left_value, left_sequence)
        if left_sequence >= right_sequence
        else (right_value, right_sequence)
    )


def _minimum_optional_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _maximum_optional_int(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _minimum_optional_datetime(
    left: datetime | None, right: datetime | None
) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _maximum_optional_datetime(
    left: datetime | None, right: datetime | None
) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
