"""Restricted eager adapters. No whole-source conversions or protocol fallback.

Private library layouts are deliberately checked and fail closed if changed.
"""

from __future__ import annotations

import sys

from .capture import _Limit, positions, spread_first


def _class(module: str, name: str):
    loaded = sys.modules.get(module)
    return getattr(loaded, name, None) if loaded is not None else None


def _safe_array(array, np) -> bool:
    if np is None or type(array) is not np.ndarray:
        return False
    # Reject memmaps, foreign owners, as_strided DummyArray and subclasses.
    owner = array
    for _ in range(8):
        if type(owner) is not np.ndarray:
            return type(owner) is bytes or type(owner) is bytearray
        if owner.base is None:
            return True
        owner = owner.base
    return False


def _array_value(c, array, index, np, *, category=True):
    dtype = array.dtype
    kind, size = dtype.kind, dtype.itemsize
    if kind in "US" and size > c.b.max_value_bytes:
        return c.omitted("oversized_fixed_cell")
    if kind not in "biufOUSMm" or (kind in "biuf" and size > 8):
        return c.omitted("unsupported_dtype")
    c.charge(reads=1)
    value = array[index]
    if kind == "U":
        return c.value(str(value), category=category)
    if kind == "S":
        return c.value(bytes(value))
    if kind in "Mm":
        c.charge(nodes=1, size=768)
        unit, step = np.datetime_data(dtype)
        return {
            "type": "temporal",
            "kind": "datetime" if kind == "M" else "duration",
            "ticks": str(value.view("i8").item()),
            "unit": unit,
            "step": step,
            "null": bool(np.isnat(value)),
        }
    return c.value(value, category=category)


def _sampling_plan(c, length):
    count = min(length, c.b.max_rows)
    # Account for position lists and bounded sorting/span scratch before making
    # them. A DataFrame shares this one plan across all its selected columns.
    c.charge(size=128 * (2 * count + 2 * c.b.exploratory_rows + 1))
    base = positions(length, count)
    candidates = positions(length, count + c.b.exploratory_rows + 1)
    available = [p for p in candidates if p not in base]
    probes = [available[i] for i in positions(len(available), c.b.exploratory_rows)]
    return spread_first(base), spread_first(probes)


def _sample(c, length, read, document, plan):
    """Keep exploratory probes separate from the base sample's denominator."""
    base, probes = plan
    saw_value = False
    if length > len(base):
        c.reason("row_budget")
    try:
        for index in base:
            c.charge(size=256)
            value = read(index)
            document["base_sample"].append({"position": index, "value": value})
            if value.get("type") not in (
                "null",
                "nonfinite",
                "omitted",
                "missing_or_unsupported",
            ) and not value.get("null", False):
                saw_value = True
        # NaN and NaT are uninformative too. Select disjoint probes across the
        # entire source, without enlarging any read/node/byte/deadline budget.
        if not saw_value:
            for index in probes:
                c.charge(size=256)
                document["exploratory"].append(
                    {"position": index, "value": read(index)}
                )
    finally:
        for key in ("base_sample", "exploratory"):
            document[key].sort(key=lambda item: item["position"])


def capture_array(c, source, document, np):
    document["source_type"] = "numpy.ndarray"
    if source.ndim > c.b.max_dimensions:
        c.reason("dimension_budget")
        return
    shape, strides, dtype = source.shape, source.strides, source.dtype
    document["metadata"] = {
        "shape": list(shape),
        "dtype_kind": source.dtype.kind,
        "itemsize": source.dtype.itemsize,
    }
    if c.options.fields:
        c.reason("unsupported_field_selection")
        return
    if not _safe_array(source, np):
        c.reason("unsafe_array_owner")
        return

    def read(flat):
        coords = []
        for dimension in reversed(shape):
            flat, position = divmod(flat, dimension)
            coords.append(position)
        return _array_value(c, source, tuple(reversed(coords)), np)

    try:
        _sample(c, source.size, read, document, _sampling_plan(c, source.size))
    finally:
        if (
            source.shape != shape
            or source.strides != strides
            or source.dtype is not dtype
        ):
            c.reason("concurrent_mutation")
            document["base_sample"] = []
            document["exploratory"] = []


def _index_array(index, pd, np):
    if type(index) is pd.Index:
        array = index._data
    elif type(index) is pd.DatetimeIndex or type(index) is pd.TimedeltaIndex:
        data = index._data
        if not any(
            type(data) is _class(module, name)
            for module, name in (
                ("pandas.core.arrays.datetimes", "DatetimeArray"),
                ("pandas.core.arrays.timedeltas", "TimedeltaArray"),
            )
        ):
            return None
        array = data._ndarray
    else:
        return None
    return array if _safe_array(array, np) and array.ndim == 1 else None


def _index_length(index, pd, np):
    if type(index) is pd.RangeIndex and type(index._range) is range:
        return len(index._range)
    array = _index_array(index, pd, np)
    if array is not None:
        return len(array)
    if type(index) is pd.MultiIndex:
        codes = index._codes
        if type(codes) is _class(
            "pandas.core.indexes.frozen", "FrozenList"
        ) and list.__len__(codes):
            first = list.__getitem__(codes, 0)
            if _safe_array(first, np) and first.ndim == 1:
                return len(first)
    return None


def _column_label(c, index, position, pd, np):
    if type(index) is pd.RangeIndex:
        return c.value(index._range[position])
    array = _index_array(index, pd, np)
    if array is not None:
        return _array_value(c, array, position, np, category=False)
    # MultiIndex shape does not require expanding/hashing its levels or values.
    return c.omitted("unsupported_column_label")


def _block_column(c, block, position, np, width):
    # indexer, len(placement), and is_slice_like can all scan the full
    # placement array. Width must bound that scan before accessing any of them.
    if width > c.b.max_fields:
        c.reason("placement_budget")
        return None
    placement = block.mgr_locs
    if type(placement) is not _class("pandas._libs.internals", "BlockPlacement"):
        return None
    indexer = placement.indexer
    if type(indexer) is slice:
        start, stop, step = indexer.start, indexer.stop, indexer.step
        if not all(type(x) is int for x in (start, stop, step)) or step <= 0:
            return None
        if start <= position < stop and (position - start) % step == 0:
            return (position - start) // step
    elif _safe_array(indexer, np) and indexer.dtype.kind in "iu" and indexer.ndim == 1:
        # Do not expand slice placements or scan arbitrary-width placements.
        if len(indexer) > c.b.max_fields:
            c.reason("fragmented_placement")
            return None
        for i in range(len(indexer)):
            c.charge(reads=1)
            if int(indexer[i]) == position:
                return i
    return None


def _existing_column_maps(manager, width, np):
    maps = manager._blknos, manager._blklocs
    if all(
        _safe_array(array, np)
        and array.ndim == 1
        and len(array) == width
        and array.dtype.kind in "iu"
        and array.dtype.itemsize <= 8
        for array in maps
    ):
        return maps
    return None


def _known_block(block):
    return any(
        type(block) is _class("pandas.core.internals.blocks", name)
        for name in (
            "NumpyBlock",
            "ExtensionBlock",
            "DatetimeLikeBlock",
            "DatetimeTZBlock",
        )
    )


def _dtype_metadata(c, array, np):
    c.charge(size=512)
    dtype = array.dtype
    result = {"kind": dtype.kind, "itemsize": dtype.itemsize}
    if dtype.kind in "Mm":
        unit, step = np.datetime_data(dtype)
        result.update(
            temporal_kind="datetime" if dtype.kind == "M" else "duration",
            unit=unit,
            step=step,
        )
    return result


def _pandas_reader(c, block, local, np):
    if not _known_block(block):
        return None, None
    array = block.values
    if type(block) is _class("pandas.core.internals.blocks", "NumpyBlock"):
        if _safe_array(array, np) and array.ndim == 2 and local < array.shape[0]:
            return lambda row: _array_value(
                c, array, (local, row), np
            ), _dtype_metadata(c, array, np)
    if type(block) is _class("pandas.core.internals.blocks", "ExtensionBlock"):
        if any(
            type(array) is _class(module, name)
            for module, name in (
                ("pandas.core.arrays.integer", "IntegerArray"),
                ("pandas.core.arrays.floating", "FloatingArray"),
                ("pandas.core.arrays.boolean", "BooleanArray"),
            )
        ):
            data, mask = array._data, array._mask
            if (
                _safe_array(data, np)
                and _safe_array(mask, np)
                and data.ndim == mask.ndim == 1
                and len(data) == len(mask)
                and mask.dtype.kind == "b"
                and local == 0
            ):

                def read(row):
                    c.charge(reads=1)
                    return (
                        c.value(None)
                        if bool(mask[row])
                        else _array_value(c, data, row, np)
                    )

                dtype = _dtype_metadata(c, data, np)
                dtype["nullable"] = True
                return read, dtype
    if any(
        type(array) is _class(module, name)
        for module, name in (
            ("pandas.core.arrays.string_", "StringArray"),
            ("pandas.core.arrays.datetimes", "DatetimeArray"),
            ("pandas.core.arrays.timedeltas", "TimedeltaArray"),
        )
    ):
        data = array._ndarray
        if (
            _safe_array(data, np)
            and data.ndim in (1, 2)
            and (local == 0 if data.ndim == 1 else local < data.shape[0])
        ):
            dtype = _dtype_metadata(c, data, np)
            if type(block) is _class("pandas.core.internals.blocks", "DatetimeTZBlock"):
                # The copied ticks are UTC; never stringify arbitrary tzinfo.
                dtype["timezone"] = "UTC"
            return (
                lambda row: _array_value(
                    c, data, row if data.ndim == 1 else (local, row), np
                )
            ), dtype
    return None, None


def capture_pandas(c, source, document, np, pd):
    document["source_type"] = "pandas.DataFrame"
    manager = source._mgr
    if type(manager) is not _class("pandas.core.internals.managers", "BlockManager"):
        c.reason("unsupported_pandas_manager")
        return
    columns, rows = manager.axes
    width, height = _index_length(columns, pd, np), _index_length(rows, pd, np)
    document["metadata"] = {"shape": [height, width], "fields": []}
    if width is None or height is None:
        c.reason("unsupported_pandas_index")
        return
    blocks = manager.blocks
    if type(blocks) is not tuple or len(blocks) > c.b.max_blocks:
        c.reason("block_budget")
        return
    storage_ids = tuple(
        id(block.values) if _known_block(block) else None for block in blocks
    )
    if any(identity is None for identity in storage_ids):
        c.reason("unsupported_pandas_block")
    column_maps = _existing_column_maps(manager, width, np)
    selected = list(range(min(width, c.b.max_fields)))
    by_position = bool(c.options.fields) and type(c.options.fields[0]) is int
    if by_position:
        selected = [x for x in c.options.fields[: c.b.max_fields] if x < width]
    if width > len(selected):
        c.reason("field_budget")
    readers = []  # Source-bound functions exist only during this synchronous call.
    try:
        # Capture schema before cells so one expensive first field cannot hide
        # later fields. No full .dtypes/.columns/schema conversion is involved.
        for position in selected:
            c.charge(size=1024)
            label = _column_label(c, columns, position, pd, np)
            if c.options.fields and not by_position:
                if not (
                    label.get("type") == "string"
                    and not label.get("truncated")
                    and not label.get("encoding_replaced")
                    and label["value"] in c.options.fields
                ):
                    continue
            field = {"position": position, "label": label}
            document["metadata"]["fields"].append(field)
            reader, dtype = None, None
            if column_maps is not None:
                c.charge(reads=2)
                block_index, local = int(column_maps[0][position]), int(
                    column_maps[1][position]
                )
                if 0 <= block_index < len(blocks) and local >= 0:
                    reader, dtype = _pandas_reader(c, blocks[block_index], local, np)
            else:
                for block, identity in zip(blocks, storage_ids):
                    if identity is None:
                        continue
                    local = _block_column(c, block, position, np, width)
                    if local is not None:
                        reader, dtype = _pandas_reader(c, block, local, np)
                        break
            if reader is None:
                field["reason"] = "unsupported_column_storage"
                c.reason("unsupported_column_storage")
            else:
                field["dtype"] = dtype
                readers.append((field, reader))
        if c.options.fields:
            fields = document["metadata"]["fields"]
            found = {
                field["position"] if by_position else field["label"]["value"]
                for field in fields
            }
            if any(value not in found for value in c.options.fields):
                c.reason("field_not_inspected_or_absent")
        plan = _sampling_plan(c, height) if readers else None
        for offset, (field, reader) in enumerate(readers):
            c.categories.clear()
            c.share_field(len(readers) - offset)
            samples = {"base_sample": [], "exploratory": []}
            document["base_sample"].append(
                {"field": field["position"], "samples": samples["base_sample"]}
            )
            document["exploratory"].append(
                {"field": field["position"], "samples": samples["exploratory"]}
            )
            try:
                _sample(c, height, reader, samples, plan)
            except _Limit as limit:
                field["reason"] = limit.args[0] if limit.args else "capture_budget"
                if not field["reason"].startswith("field_"):
                    raise
            finally:
                c.field_limits = None
    finally:
        if (
            source._mgr is not manager
            or manager.axes[0] is not columns
            or manager.axes[1] is not rows
            or manager.blocks is not blocks
            or any(
                id(block.values) != identity
                for block, identity in zip(blocks, storage_ids)
                if identity is not None
            )
        ):
            c.reason("concurrent_mutation")
            document["base_sample"] = []
            document["exploratory"] = []


def capture_polars(c, source, document, pl):
    # PyDataFrame.to_series can materialize/cache an entire ScalarColumn.
    # Even height/width acquire native locks. Until a bounded, nonblocking
    # storage interface exists, never touch native state or typed getters.
    document["source_type"] = "polars.DataFrame"
    c.reason("polars_capture_unavailable")
