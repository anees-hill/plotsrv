# src/plotsrv/json_model.py
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

try:  # pragma: no cover
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:  # pragma: no cover
    import polars as pl  # type: ignore
except Exception:  # pragma: no cover
    pl = None  # type: ignore[assignment]

try:  # pragma: no cover
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover
    Figure = None  # type: ignore[assignment]

try:  # pragma: no cover
    from plotnine.ggplot import ggplot as PlotnineGGPlot  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    PlotnineGGPlot = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class JsonModelLimits:
    max_depth: int = 12
    max_nodes: int = 5000
    max_dict_items: int = 200
    max_list_items: int = 200
    max_preview_chars: int = 120
    max_string_chars: int = 1000


@dataclass(slots=True)
class _BuildCtx:
    limits: JsonModelLimits
    nodes_seen: int = 0
    max_depth_seen: int = 0
    truncated: bool = False


def build_json_document(
    obj: Any,
    *,
    source_format: str,
    raw_text: str | None = None,
    source_filename: str | None = None,
    limits: JsonModelLimits | None = None,
) -> dict[str, Any]:
    """
    Build a renderer-friendly JSON document payload.

    This is the new canonical payload for artifact_kind="json".
    """
    lim = limits or JsonModelLimits()
    ctx = _BuildCtx(limits=lim)

    root = _build_node(
        obj,
        ctx=ctx,
        path=[],
        depth=0,
        display_key="root",
        parent_label="root",
    )

    pretty_text = build_pretty_text(obj)

    return {
        "type": "plotsrv_json_document",
        "version": 1,
        "source_format": str(source_format or "python_object"),
        "raw_text": raw_text,
        "pretty_text": pretty_text,
        "root": root,
        "meta": {
            "node_count": ctx.nodes_seen,
            "max_depth_seen": ctx.max_depth_seen,
            "truncated": ctx.truncated,
            "source_filename": source_filename,
        },
    }


def build_pretty_text(obj: Any) -> str:
    """
    Best-effort pretty text representation for Text mode.
    """
    try:
        return json.dumps(_to_json_compatible(obj), indent=2, ensure_ascii=False)
    except Exception:
        try:
            return repr(obj)
        except Exception:
            return "<unrepresentable>"


def classify_json_value(obj: Any) -> dict[str, str | None]:
    """
    Classify a value for the richer JSON UI.

    Returns:
      {
        "node_kind": ...,
        "value_kind": ...,
        "type_label": ...,
        "icon_key": ...,
      }
    """
    if isinstance(obj, dict):
        return {
            "node_kind": "container",
            "value_kind": "dict",
            "type_label": "dict",
            "icon_key": "json",
        }

    if isinstance(obj, (list, tuple, set)):
        return {
            "node_kind": "container",
            "value_kind": "list",
            "type_label": type(obj).__name__,
            "icon_key": "json",
        }

    if _is_dataframe(obj):
        return {
            "node_kind": "leaf_artifact",
            "value_kind": "table",
            "type_label": type(obj).__name__,
            "icon_key": "table",
        }

    if _looks_like_plot(obj):
        return {
            "node_kind": "leaf_artifact",
            "value_kind": "plot",
            "type_label": type(obj).__name__,
            "icon_key": "plot",
        }

    if looks_like_image_payload(obj):
        return {
            "node_kind": "leaf_artifact",
            "value_kind": "image",
            "type_label": "image",
            "icon_key": "image",
        }

    if _looks_like_ndarray(obj):
        return {
            "node_kind": "leaf_artifact",
            "value_kind": "array",
            "type_label": type(obj).__name__,
            "icon_key": "python",
        }

    if _is_scalar(obj):
        return {
            "node_kind": "scalar",
            "value_kind": type(obj).__name__,
            "type_label": type(obj).__name__,
            "icon_key": None,
        }

    return {
        "node_kind": "leaf_artifact",
        "value_kind": "python",
        "type_label": type(obj).__name__,
        "icon_key": "python",
    }


def looks_like_image_payload(obj: Any) -> bool:
    return isinstance(obj, dict) and "data_b64" in obj and "mime" in obj


def _build_node(
    obj: Any,
    *,
    ctx: _BuildCtx,
    path: list[str | int],
    depth: int,
    display_key: str,
    parent_label: str,
) -> dict[str, Any]:
    ctx.nodes_seen += 1
    ctx.max_depth_seen = max(ctx.max_depth_seen, depth)

    if ctx.nodes_seen > ctx.limits.max_nodes:
        ctx.truncated = True
        return _make_truncated_node(
            path=path,
            depth=depth,
            display_key=display_key,
            reason="node limit",
        )

    cls = classify_json_value(obj)

    base: dict[str, Any] = {
        "id": _make_path_id(path),
        "path": [_json_path_part(x) for x in path],
        "depth": depth,
        "label": parent_label,
        "display_key": display_key,
        "node_kind": cls["node_kind"],
        "value_kind": cls["value_kind"],
        "type_label": cls["type_label"],
        "icon_key": cls["icon_key"],
        "summary": None,
        "preview": None,
        "child_count": 0,
        "descendant_count": 0,
        "descendant_layer_count": 0,
        "expandable": False,
        "children": [],
        "truncated": False,
        "truncation_reason": None,
    }

    if isinstance(obj, dict):
        if depth >= ctx.limits.max_depth:
            ctx.truncated = True
            base["summary"] = _summarise_container(obj)
            base["expandable"] = True
            base["truncated"] = True
            base["truncation_reason"] = "depth limit"
            base["child_count"] = len(obj)
            base["descendant_count"] = _count_descendants(obj)
            base["descendant_layer_count"] = _count_remaining_layers(obj)
            return base

        items = list(obj.items())
        shown = items[: ctx.limits.max_dict_items]
        if len(items) > len(shown):
            ctx.truncated = True
            base["truncated"] = True
            base["truncation_reason"] = "dict item limit"

        children: list[dict[str, Any]] = []
        for k, v in shown:
            child_path = [*path, str(k)]
            children.append(
                _build_node(
                    v,
                    ctx=ctx,
                    path=child_path,
                    depth=depth + 1,
                    display_key=str(k),
                    parent_label=str(k),
                )
            )

        base["children"] = children
        base["child_count"] = len(items)
        base["expandable"] = True
        base["summary"] = _summarise_container(obj)
        base["preview"] = None
        base["descendant_count"] = _count_descendants(obj)
        base["descendant_layer_count"] = _count_remaining_layers(obj)
        return base

    if isinstance(obj, (list, tuple, set)):
        xs = list(obj)
        if depth >= ctx.limits.max_depth:
            ctx.truncated = True
            base["summary"] = _summarise_container(xs)
            base["expandable"] = True
            base["truncated"] = True
            base["truncation_reason"] = "depth limit"
            base["child_count"] = len(xs)
            base["descendant_count"] = _count_descendants(xs)
            base["descendant_layer_count"] = _count_remaining_layers(xs)
            return base

        shown = xs[: ctx.limits.max_list_items]
        if len(xs) > len(shown):
            ctx.truncated = True
            base["truncated"] = True
            base["truncation_reason"] = "list item limit"

        children: list[dict[str, Any]] = []
        for i, v in enumerate(shown):
            child_path = [*path, i]
            children.append(
                _build_node(
                    v,
                    ctx=ctx,
                    path=child_path,
                    depth=depth + 1,
                    display_key=f"[{i}]",
                    parent_label=f"[{i}]",
                )
            )

        base["children"] = children
        base["child_count"] = len(xs)
        base["expandable"] = True
        base["summary"] = _summarise_container(xs)
        base["preview"] = None
        base["descendant_count"] = _count_descendants(xs)
        base["descendant_layer_count"] = _count_remaining_layers(xs)
        return base

    if cls["node_kind"] == "scalar":
        preview = _safe_preview(obj, max_chars=ctx.limits.max_preview_chars)
        base["summary"] = preview
        base["preview"] = preview
        return base

    preview = _summarise_leaf_artifact(obj, max_chars=ctx.limits.max_preview_chars)
    base["summary"] = preview
    base["preview"] = preview
    return base


def _make_truncated_node(
    *,
    path: list[str | int],
    depth: int,
    display_key: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "id": _make_path_id(path),
        "path": [_json_path_part(x) for x in path],
        "depth": depth,
        "label": display_key,
        "display_key": display_key,
        "node_kind": "scalar",
        "value_kind": "truncated",
        "type_label": "truncated",
        "icon_key": None,
        "summary": "…",
        "preview": "…",
        "child_count": 0,
        "descendant_count": 0,
        "descendant_layer_count": 0,
        "expandable": False,
        "children": [],
        "truncated": True,
        "truncation_reason": reason,
    }


def _make_path_id(path: list[str | int]) -> str:
    if not path:
        return "root"
    parts = []
    for p in path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            parts.append(str(p))
    return "root/" + "/".join(parts)


def _json_path_part(x: str | int) -> str | int:
    return x


def _summarise_container(obj: Any) -> str:
    if isinstance(obj, dict):
        n = len(obj)
        return f"{n} key" if n == 1 else f"{n} keys"

    if isinstance(obj, list):
        n = len(obj)
        return f"{n} item" if n == 1 else f"{n} items"

    if isinstance(obj, tuple):
        n = len(obj)
        return f"{n} item" if n == 1 else f"{n} items"

    if isinstance(obj, set):
        n = len(obj)
        return f"{n} item" if n == 1 else f"{n} items"

    return type(obj).__name__


def _summarise_leaf_artifact(obj: Any, *, max_chars: int) -> str:
    if _is_dataframe(obj):
        try:
            shape = getattr(obj, "shape", None)
            if shape is not None and len(shape) == 2:
                return f"{type(obj).__name__} · {shape[0]} rows × {shape[1]} cols"
        except Exception:
            pass
        return type(obj).__name__

    if _looks_like_plot(obj):
        return type(obj).__name__

    if looks_like_image_payload(obj):
        return "image payload"

    if _looks_like_ndarray(obj):
        try:
            shape = getattr(obj, "shape", None)
            if shape is not None:
                return f"{type(obj).__name__} · shape={list(shape)}"
        except Exception:
            pass
        return type(obj).__name__

    return _safe_preview(repr(obj), max_chars=max_chars)


def _safe_preview(value: Any, *, max_chars: int) -> str:
    try:
        s = str(value)
    except Exception:
        try:
            s = repr(value)
        except Exception:
            s = "<unrepresentable>"

    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "…"


def _count_descendants(obj: Any) -> int:
    if isinstance(obj, dict):
        total = len(obj)
        for v in obj.values():
            total += _count_descendants(v)
        return total

    if isinstance(obj, (list, tuple, set)):
        total = len(obj)
        for v in obj:
            total += _count_descendants(v)
        return total

    return 0


def _count_remaining_layers(obj: Any) -> int:
    if isinstance(obj, dict):
        if not obj:
            return 0
        return 1 + max(_count_remaining_layers(v) for v in obj.values())

    if isinstance(obj, (list, tuple, set)):
        xs = list(obj)
        if not xs:
            return 0
        return 1 + max(_count_remaining_layers(v) for v in xs)

    return 0


def _to_json_compatible(obj: Any) -> Any:
    if obj is None:
        return None

    if isinstance(obj, (str, int, bool)):
        return obj

    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            return None
        return obj

    if isinstance(obj, dict):
        return {str(k): _to_json_compatible(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [_to_json_compatible(v) for v in obj]

    if _is_dataframe(obj):
        try:
            if hasattr(obj, "head"):
                sample = obj.head(20)
                if hasattr(sample, "to_dict"):
                    try:
                        return {
                            "type": type(obj).__name__,
                            "shape": list(getattr(obj, "shape", (None, None))),
                            "sample": sample.to_dict(orient="records"),
                        }
                    except Exception:
                        pass
        except Exception:
            pass
        return {"type": type(obj).__name__}

    if _looks_like_plot(obj):
        return {"type": type(obj).__name__}

    if looks_like_image_payload(obj):
        return {
            "type": "image",
            "mime": obj.get("mime"),
            "filename": obj.get("filename"),
        }

    if _looks_like_ndarray(obj):
        try:
            shape = getattr(obj, "shape", None)
            return {
                "type": type(obj).__name__,
                "shape": list(shape) if shape is not None else None,
            }
        except Exception:
            return {"type": type(obj).__name__}

    try:
        import numpy as np  # type: ignore

        if isinstance(obj, np.generic):
            return _to_json_compatible(obj.item())
    except Exception:
        pass

    return repr(obj)


def _is_scalar(obj: Any) -> bool:
    return obj is None or isinstance(obj, (str, int, float, bool))


def _is_dataframe(obj: Any) -> bool:
    if pd is not None and isinstance(obj, pd.DataFrame):  # type: ignore[arg-type]
        return True
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return True
    return False


def _looks_like_plot(obj: Any) -> bool:
    if Figure is not None and isinstance(obj, Figure):  # type: ignore[arg-type]
        return True

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return True

    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return True

    return False


def _looks_like_ndarray(obj: Any) -> bool:
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, np.ndarray):
            return True
    except Exception:
        pass

    try:
        import torch  # type: ignore

        if isinstance(obj, torch.Tensor):
            return True
    except Exception:
        pass

    return False
