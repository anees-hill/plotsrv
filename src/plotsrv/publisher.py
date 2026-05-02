# src/plotsrv/publisher.py
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
import math
from pathlib import Path
from typing import Any

import pandas as pd

from . import config
from .backends import df_to_html_simple, df_to_rich_sample, fig_to_png_bytes
from .file_kinds import coerce_file_to_publishable
from .json_model import build_json_document

try:  # pragma: no cover
    import polars as pl  # type: ignore
except Exception:  # pragma: no cover
    pl = None  # type: ignore[assignment]

try:  # pragma: no cover
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except Exception:  # pragma: no cover
    plt = None  # type: ignore[assignment]
    Figure = None  # type: ignore[assignment]

try:  # pragma: no cover
    from plotnine.ggplot import ggplot as PlotnineGGPlot  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    PlotnineGGPlot = None  # type: ignore[assignment]


def _is_na(x: Any) -> bool:
    try:
        res = pd.isna(x)
    except Exception:
        return False

    if isinstance(res, bool):
        return res

    try:
        import numpy as np  # type: ignore

        if isinstance(res, np.bool_):  # pragma: no cover
            return bool(res)
    except Exception:
        pass

    return False


def _json_safe(x: Any) -> Any:
    if x is None:
        return None

    if isinstance(x, dict):
        return {str(k): _json_safe(v) for k, v in x.items()}

    if isinstance(x, (list, tuple, set)):
        return [_json_safe(v) for v in x]

    if isinstance(x, (str, int, bool)):
        return x

    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return x

    if isinstance(x, (datetime, date)):
        return x.isoformat()

    if _is_na(x):
        return None

    try:
        import numpy as np  # type: ignore

        if isinstance(x, np.generic):
            return _json_safe(x.item())
    except Exception:
        pass

    return str(x)


def _is_dataframe(obj: Any) -> bool:
    if isinstance(obj, pd.DataFrame):
        return True
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        return True
    return False


def _to_dataframe(obj: Any) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj
    if pl is not None and isinstance(obj, pl.DataFrame):  # type: ignore[arg-type]
        try:
            return obj.to_pandas()
        except Exception:
            return pd.DataFrame(obj.to_dicts())
    raise TypeError(f"Expected pandas/polars DataFrame, got {type(obj)!r}")


def _to_figure(obj: Any | None) -> Any:
    if plt is None:
        raise RuntimeError("matplotlib is not available; cannot publish plot")

    if obj is None:
        return plt.gcf()

    if Figure is not None and isinstance(obj, Figure):  # type: ignore[arg-type]
        return obj

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return obj.draw()

    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return obj.draw()

    raise TypeError(
        "Cannot publish plot: expected matplotlib.figure.Figure, plotnine.ggplot, or None; "
        f"got {type(obj)!r}"
    )


def _infer_artifact_kind(obj: Any) -> str:
    if isinstance(obj, str):
        return "text"
    if isinstance(obj, (dict, list, tuple, set)):
        return "json"
    if _try_array_payload(obj) is not None:
        return "json"
    return "python"


def _looks_like_plot(obj: Any) -> bool:
    if obj is None:
        return True

    if Figure is not None and isinstance(obj, Figure):  # type: ignore[arg-type]
        return True

    if PlotnineGGPlot is not None and isinstance(obj, PlotnineGGPlot):  # type: ignore[arg-type]
        return True

    if hasattr(obj, "draw") and obj.__class__.__module__.startswith("plotnine"):
        return True

    return False


def _try_array_payload(obj: Any) -> dict[str, Any] | None:
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, np.ndarray):
            arr = obj
            payload: dict[str, Any] = {
                "type": "numpy.ndarray",
                "dtype": str(arr.dtype),
                "shape": list(arr.shape),
                "ndim": int(arr.ndim),
                "size": int(arr.size),
            }

            max_elems = 2000
            if arr.size <= max_elems:
                payload["data"] = arr.tolist()
                payload["truncated"] = False
            else:
                flat = arr.ravel()[:max_elems]
                payload["data"] = flat.tolist()
                payload["truncated"] = True
                payload["truncation_reason"] = (
                    f"sampled first {max_elems} elements from flattened array"
                )
            return payload
    except Exception:
        pass

    try:
        import torch  # type: ignore

        if isinstance(obj, torch.Tensor):
            t = obj.detach()
            payload = {
                "type": "torch.Tensor",
                "dtype": str(t.dtype).replace("torch.", ""),
                "shape": list(t.shape),
                "ndim": int(t.ndim),
                "device": str(t.device),
                "requires_grad": bool(getattr(t, "requires_grad", False)),
                "numel": int(t.numel()),
            }

            max_elems = 2000
            if t.numel() <= max_elems:
                payload["data"] = t.cpu().tolist()
                payload["truncated"] = False
            else:
                flat = t.reshape(-1)[:max_elems].cpu().tolist()
                payload["data"] = flat
                payload["truncated"] = True
                payload["truncation_reason"] = (
                    f"sampled first {max_elems} elements from flattened tensor"
                )
            return payload
    except Exception:
        pass

    return None


def _to_json_artifact_document(
    obj: Any,
    *,
    raw_text: str | None = None,
    source_format: str = "python_object",
    source_filename: str | None = None,
) -> dict[str, Any]:
    if _is_json_artifact_document(obj):
        return obj

    if _try_array_payload(obj) is not None:
        array_payload = _try_array_payload(obj)
        return build_json_document(
            array_payload,
            source_format=source_format,
            raw_text=raw_text,
            source_filename=source_filename,
        )

    return build_json_document(
        obj,
        source_format=source_format,
        raw_text=raw_text,
        source_filename=source_filename,
    )


def _is_json_artifact_document(obj: Any) -> bool:
    return isinstance(obj, dict) and obj.get("type") == "plotsrv_json_document"


def _to_publish_payload(
    obj: Any,
    *,
    kind: str,
    label: str,
    section: str | None,
    update_limit_s: int | None,
    force: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "label": label,
        "section": section,
        "update_limit_s": update_limit_s,
        "force": force,
    }

    if kind == "plot":
        fig = _to_figure(obj)
        png = fig_to_png_bytes(fig)
        try:
            if plt is not None:
                plt.close(fig)
        except Exception:
            pass
        payload["plot_png_b64"] = base64.b64encode(png).decode("utf-8")
        return payload

    if kind == "table":
        df = _to_dataframe(obj)
        payload["table"] = df_to_rich_sample(
            df, max_rows=config.get_max_table_rows_rich()
        )
        payload["table_html_simple"] = df_to_html_simple(
            df, max_rows=config.get_max_table_rows_simple()
        )
        return payload

    if kind == "artifact":
        if isinstance(obj, dict) and "html" in obj:
            payload["artifact_kind"] = "html"
            payload["artifact"] = _json_safe(obj)
            return payload

        artifact_kind = _infer_artifact_kind(obj)
        payload["artifact_kind"] = artifact_kind

        if artifact_kind == "text":
            if isinstance(obj, (bytes, bytearray)):
                payload["artifact"] = bytes(obj).decode("utf-8", errors="replace")
            else:
                payload["artifact"] = str(obj)

        elif artifact_kind == "json":
            payload["artifact"] = _json_safe(
                _to_json_artifact_document(
                    obj,
                    source_format="python_object",
                    raw_text=None,
                    source_filename=None,
                )
            )

        else:
            payload["artifact"] = repr(obj)

        return payload

    raise ValueError(f"Unknown publish kind: {kind!r}")


def publish_artifact(
    obj: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    label: str,
    section: str | None = None,
    artifact_kind: str | None = None,
    update_limit_s: int | None = None,
    force: bool = False,
) -> None:
    debug = os.environ.get("PLOTSRV_DEBUG", "").strip() == "1"

    if artifact_kind == "html" and isinstance(obj, str):
        obj = {"html": obj, "unsafe": True}

    # Path-like publishing
    if not isinstance(obj, (str, bytes, bytearray)):
        p: Path | None
        try:
            p = Path(obj)  # type: ignore[arg-type]
        except Exception:
            p = None

        is_pathlike = p is not None and (
            isinstance(obj, Path) or getattr(obj, "__fspath__", None) is not None
        )

        if is_pathlike:
            try:
                path = p.expanduser().resolve()
                if path.exists() and path.is_file():
                    coerced = coerce_file_to_publishable(path)

                    if coerced.publish_kind == "table":
                        return publish_view(
                            coerced.obj,
                            host=host,
                            port=port,
                            label=label,
                            section=section,
                            update_limit_s=update_limit_s,
                            force=force,
                            kind="table",
                        )

                    ak = artifact_kind or coerced.artifact_kind or "text"

                    if ak == "html":
                        return publish_artifact(
                            {"html": str(coerced.obj), "unsafe": True},
                            host=host,
                            port=port,
                            label=label,
                            section=section,
                            artifact_kind="html",
                            update_limit_s=update_limit_s,
                            force=force,
                        )

                    if ak == "json":
                        doc = (
                            coerced.obj
                            if _is_json_artifact_document(coerced.obj)
                            else _to_json_artifact_document(
                                coerced.obj,
                                raw_text=coerced.raw_text,
                                source_format=coerced.source_format or "python_object",
                                source_filename=coerced.source_filename,
                            )
                        )

                        return publish_artifact(
                            doc,
                            host=host,
                            port=port,
                            label=label,
                            section=section,
                            artifact_kind="json",
                            update_limit_s=update_limit_s,
                            force=force,
                        )

                    return publish_artifact(
                        coerced.obj,
                        host=host,
                        port=port,
                        label=label,
                        section=section,
                        artifact_kind=ak,
                        update_limit_s=update_limit_s,
                        force=force,
                    )
            except Exception as e:
                if debug:
                    raise
                return publish_artifact(
                    f"[plotsrv] file read/parse error: {type(e).__name__}: {e}",
                    host=host,
                    port=port,
                    label=label,
                    section=section,
                    artifact_kind="text",
                    update_limit_s=update_limit_s,
                    force=force,
                )

    if artifact_kind is None:
        if _is_dataframe(obj):
            return publish_view(
                obj,
                host=host,
                port=port,
                label=label,
                section=section,
                update_limit_s=update_limit_s,
                force=force,
                kind="table",
            )

        if _looks_like_plot(obj):
            return publish_view(
                obj,
                host=host,
                port=port,
                label=label,
                section=section,
                update_limit_s=update_limit_s,
                force=force,
                kind="plot",
            )

    kind2 = (artifact_kind or "").strip().lower() or None
    if kind2 is None:
        if isinstance(obj, (dict, list, tuple)):
            kind2 = "json"
        elif isinstance(obj, (str, bytes, bytearray)):
            kind2 = "text"
        else:
            kind2 = "python"

    payload = _to_publish_payload(
        obj,
        kind="artifact",
        label=label,
        section=section,
        update_limit_s=update_limit_s,
        force=force,
    )

    if artifact_kind is not None:
        payload["artifact_kind"] = artifact_kind

    payload = _json_safe(payload)

    url = f"http://{host}:{port}/publish"
    try:
        data = json.dumps(payload).encode("utf-8")
    except Exception:
        if debug:
            raise
        return

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as e:
        if debug:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"plotsrv publish failed: {e.code} {e.reason}\n{body}"
            ) from e
        return
    except Exception:
        if debug:
            raise
        return


def publish_view(
    obj: Any,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    label: str,
    section: str | None = None,
    update_limit_s: int | None = None,
    force: bool = False,
    kind: str | None = None,
) -> None:
    debug = os.environ.get("PLOTSRV_DEBUG", "").strip() == "1"

    if kind is None:
        kind2 = "table" if _is_dataframe(obj) else "plot"
    else:
        kind2 = kind

    try:
        payload = _to_publish_payload(
            obj,
            kind=kind2,
            label=label,
            section=section,
            update_limit_s=update_limit_s,
            force=force,
        )
    except Exception:
        if debug:
            raise
        return

    payload = _json_safe(payload)

    url = f"http://{host}:{port}/publish"
    try:
        data = json.dumps(payload).encode("utf-8")
    except Exception:
        if debug:
            raise
        return

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as e:
        if debug:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(
                f"plotsrv publish failed: {e.code} {e.reason}\n{body}"
            ) from e
        return
    except Exception:
        if debug:
            raise
        return


def plot_launch(
    obj: Any,
    *,
    label: str,
    section: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    update_limit_s: int | None = None,
    force: bool = False,
) -> None:
    publish_view(
        obj,
        host=host,
        port=port,
        label=label,
        section=section,
        update_limit_s=update_limit_s,
        force=force,
    )
