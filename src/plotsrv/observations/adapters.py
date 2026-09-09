"""Restricted eager adapters. No whole-source conversions or protocol fallback.

Private library layouts are deliberately checked and fail closed if changed.
"""

from __future__ import annotations

import sys

from .capture import positions


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
            "ticks": str(value.view("i8").item()),
            "unit": unit,
            "step": step,
            "null": bool(np.isnat(value)),
        }
    return c.value(value, category=category)


def _sample(c, length, read, document):
    """Keep exploratory probes separate from the base sample's denominator."""
    base = positions(length, c.b.max_rows)
    saw_value = False
    for index in base:
        c.charge(size=256)
        value = read(index)
        document["base_sample"].append({"position": index, "value": value})
        if value.get("type") not in ("null", "omitted", "missing_or_unsupported"):
            saw_value = True
    if length > len(base):
        c.reason("row_budget")
    # Probe interior offsets only when the base supplied no usable values.
    if not saw_value and c.b.exploratory_rows:
        candidates = positions(
            length, min(128, c.b.max_rows + c.b.exploratory_rows + 1)
        )
        for index in (p for p in candidates if p not in base):
            if len(document["exploratory"]) >= c.b.exploratory_rows:
                break
            c.charge(size=256)
            document["exploratory"].append({"position": index, "value": read(index)})


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
        _sample(c, source.size, read, document)
    finally:
        if (
            source.shape != shape
            or source.strides != strides
            or source.dtype is not dtype
        ):
            c.reason("concurrent_mutation")
            document["base_sample"] = []
            document["exploratory"] = []


def _index_length(index, pd, np):
    if type(index) is pd.RangeIndex and type(index._range) is range:
        return len(index._range)
    if type(index) is pd.Index and _safe_array(index._data, np):
        return len(index._data)
    return None


def _column_label(c, index, position, pd, np):
    if type(index) is pd.RangeIndex:
        return c.value(index._range[position])
    return _array_value(c, index._data, position, np, category=False)


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


def _pandas_reader(c, block, local, np):
    if type(block) is _class("pandas.core.internals.blocks", "NumpyBlock"):
        array = block.values
        if _safe_array(array, np) and array.ndim == 2:
            return lambda row: _array_value(c, array, (local, row), np)
    if type(block) is _class("pandas.core.internals.blocks", "ExtensionBlock"):
        array = block.values
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
                and mask.dtype.kind == "b"
            ):

                def read(row):
                    c.charge(reads=1)
                    return (
                        {"type": "null"}
                        if bool(mask[row])
                        else _array_value(c, data, row, np)
                    )

                return read
        if any(
            type(array) is _class(module, name)
            for module, name in (
                ("pandas.core.arrays.string_", "StringArray"),
                ("pandas.core.arrays.datetimes", "DatetimeArray"),
                ("pandas.core.arrays.timedeltas", "TimedeltaArray"),
            )
        ):
            data = array._ndarray
            if _safe_array(data, np) and data.ndim in (1, 2):
                return lambda row: _array_value(
                    c, data, row if data.ndim == 1 else (local, row), np
                )
    return None


def capture_pandas(c, source, document, np, pd):
    document["source_type"] = "pandas.DataFrame"
    manager = source._mgr
    if type(manager) is not _class("pandas.core.internals.managers", "BlockManager"):
        c.reason("unsupported_pandas_manager")
        return
    columns, rows = manager.axes
    width, height = _index_length(columns, pd, np), _index_length(rows, pd, np)
    if width is None or height is None:
        c.reason("unsupported_pandas_index")
        return
    document["metadata"] = {"shape": [height, width], "fields": []}
    blocks = manager.blocks
    if type(blocks) is not tuple or len(blocks) > c.b.max_blocks:
        c.reason("block_budget")
        return
    if any(
        type(block) is not _class("pandas.core.internals.blocks", "NumpyBlock")
        and type(block) is not _class("pandas.core.internals.blocks", "ExtensionBlock")
        for block in blocks
    ):
        c.reason("unsupported_pandas_block")
        return
    storage_ids = tuple(id(block.values) for block in blocks)
    column_maps = _existing_column_maps(manager, width, np)
    selected = list(range(min(width, c.b.max_fields)))
    if c.options.fields and all(type(x) is int for x in c.options.fields):
        selected = [x for x in c.options.fields[: c.b.max_fields] if x < width]
    if width > len(selected):
        c.reason("field_budget")
    try:
        for position in selected:
            c.categories.clear()
            c.charge(size=512)
            label = _column_label(c, columns, position, pd, np)
            if c.options.fields and not all(type(x) is int for x in c.options.fields):
                if not any(
                    type(x) is str
                    and label.get("type") == "string"
                    and not label.get("truncated")
                    and not label.get("encoding_replaced")
                    and label["value"] == x
                    for x in c.options.fields
                ):
                    continue
            field = {"position": position, "label": label}
            document["metadata"]["fields"].append(field)
            reader = None
            if column_maps is not None:
                c.charge(reads=2)
                block_index = int(column_maps[0][position])
                local = int(column_maps[1][position])
                if 0 <= block_index < len(blocks) and local >= 0:
                    reader = _pandas_reader(c, blocks[block_index], local, np)
            else:
                for block in blocks:
                    local = _block_column(c, block, position, np, width)
                    if local is not None:
                        reader = _pandas_reader(c, block, local, np)
                        break
            if reader is None:
                field["reason"] = "unsupported_column_storage"
                c.reason("unsupported_column_storage")
                continue
            samples = {"base_sample": [], "exploratory": []}
            # Insert first so a structural limit preserves already-captured evidence.
            document["base_sample"].append(
                {"field": position, "samples": samples["base_sample"]}
            )
            document["exploratory"].append(
                {"field": position, "samples": samples["exploratory"]}
            )
            _sample(c, height, reader, samples)
    finally:
        if (
            source._mgr is not manager
            or manager.axes[0] is not columns
            or manager.axes[1] is not rows
            or manager.blocks is not blocks
            or any(
                id(block.values) != identity
                for block, identity in zip(blocks, storage_ids)
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
