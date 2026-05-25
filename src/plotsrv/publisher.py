# src/plotsrv/publisher.py
from __future__ import annotations

import base64
import json
import math
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from . import config
from .backends import df_to_html_simple, df_to_rich_sample, fig_to_png_bytes
from .file_kinds import coerce_file_to_publishable
from .json_model import build_json_document

PublishMode = Literal["auto", "local", "remote"]

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


def _debug_enabled() -> bool:
    return os.environ.get("PLOTSRV_DEBUG", "").strip() == "1"


def _post_publish_payload(
    *,
    payload: dict[str, Any],
    host: str,
    port: int,
    debug: bool,
) -> None:
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


def _to_publish_payload(
    obj: Any,
    *,
    kind: str,
    label: str | None,
    section: str | None,
    view_id: str | None = None,
    update_limit_s: int | None,
    force: bool,
    artifact_kind: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "label": label,
        "section": section,
        "update_limit_s": update_limit_s,
        "force": force,
    }

    if view_id is not None:
        payload["view_id"] = view_id

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
        requested_kind = (artifact_kind or "").strip().lower() or None

        if requested_kind == "html" and isinstance(obj, str):
            obj = {"html": obj, "unsafe": True}

        if isinstance(obj, dict) and "html" in obj and requested_kind in (None, "html"):
            payload["artifact_kind"] = "html"
            payload["artifact"] = _json_safe(obj)
            return payload

        kind2 = requested_kind or _infer_artifact_kind(obj)
        payload["artifact_kind"] = kind2

        if kind2 == "text":
            if isinstance(obj, (bytes, bytearray)):
                payload["artifact"] = bytes(obj).decode("utf-8", errors="replace")
            else:
                payload["artifact"] = str(obj)

        elif kind2 == "json":
            payload["artifact"] = _json_safe(
                _to_json_artifact_document(
                    obj,
                    source_format="python_object",
                    raw_text=None,
                    source_filename=None,
                )
            )

        elif kind2 == "html":
            if isinstance(obj, dict):
                payload["artifact"] = _json_safe(obj)
            else:
                payload["artifact"] = {"html": str(obj), "unsafe": True}

        elif kind2 == "markdown":
            payload["artifact"] = obj if isinstance(obj, dict) else str(obj)

        elif kind2 == "image":
            payload["artifact"] = _json_safe(obj)

        else:
            # "python" and any unknown explicit artifact kind use repr fallback.
            payload["artifact"] = repr(obj)

        return payload

    raise ValueError(f"Unknown publish kind: {kind!r}")


def _try_publish_pathlike_view(
    obj: Any,
    *,
    launch_server: bool,
    host: str | None,
    port: int | None,
    label: str | None,
    section: str | None,
    view_id: str | None,
    artifact_kind: str | None,
    update_limit_s: int | None,
    force: bool,
    debug: bool,
) -> bool:
    """
    Publish a Path-like object if obj is a real filesystem path.

    Strings are deliberately not treated as paths:
      publish_view("app.log", label="x") publishes the literal text "app.log"
      publish_view(Path("app.log"), label="x") publishes the file content
    """
    if isinstance(obj, (str, bytes, bytearray)):
        return False

    try:
        p = Path(obj)  # type: ignore[arg-type]
    except Exception:
        return False

    is_pathlike = isinstance(obj, Path) or getattr(obj, "__fspath__", None) is not None
    if not is_pathlike:
        return False

    try:
        path = p.expanduser().resolve()
        if not path.exists() or not path.is_file():
            return False

        coerced = coerce_file_to_publishable(path)

        if coerced.publish_kind == "table":
            publish_view(
                coerced.obj,
                launch_server=launch_server,
                host=host,
                port=port,
                label=label,
                section=section,
                view_id=view_id,
                update_limit_s=update_limit_s,
                force=force,
                kind="table",
            )
            return True

        ak = artifact_kind or coerced.artifact_kind or "text"

        if ak == "html":
            publish_view(
                {"html": str(coerced.obj), "unsafe": True},
                launch_server=launch_server,
                host=host,
                port=port,
                label=label,
                section=section,
                view_id=view_id,
                artifact_kind="html",
                update_limit_s=update_limit_s,
                force=force,
                kind="artifact",
            )
            return True

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

            publish_view(
                doc,
                launch_server=launch_server,
                host=host,
                port=port,
                label=label,
                section=section,
                view_id=view_id,
                artifact_kind="json",
                update_limit_s=update_limit_s,
                force=force,
                kind="artifact",
            )
            return True

        publish_view(
            coerced.obj,
            launch_server=launch_server,
            host=host,
            port=port,
            label=label,
            section=section,
            view_id=view_id,
            artifact_kind=ak,
            update_limit_s=update_limit_s,
            force=force,
            kind="artifact",
        )
        return True

    except Exception as e:
        if debug:
            raise

        publish_view(
            f"[plotsrv] file read/parse error: {type(e).__name__}: {e}",
            launch_server=launch_server,
            host=host,
            port=port,
            label=label,
            section=section,
            view_id=view_id,
            artifact_kind="text",
            update_limit_s=update_limit_s,
            force=force,
            kind="artifact",
        )
        return True


def _normalise_publish_mode(mode: PublishMode | str | None) -> PublishMode:
    raw = str(mode or "auto").strip().lower()
    if raw not in ("auto", "local", "remote"):
        raise ValueError("publish_view mode must be one of: 'auto', 'local', 'remote'")
    return raw  # type: ignore[return-value]


def _resolve_launch_server(
    *,
    launch_server: bool | None,
    mode: PublishMode | str | None,
    host: str | None,
    port: int | None,
) -> bool:
    """
    Resolve legacy mode=... and launch_server=... into one decision.

    Preferred API:
      - launch_server=True  => attached in-process server
      - launch_server=False => publish over HTTP to existing server

    Compatibility:
      - mode="local"  => launch_server=True
      - mode="remote" => launch_server=False
      - mode="auto"   => host/port omitted means local; host/port supplied means remote
      - omitted mode   => same as mode="auto"
    """
    if launch_server is not None:
        # Validate mode if the user supplied it as well, so debug/error behaviour
        # remains useful for accidental bad mode values.
        if mode is not None:
            _normalise_publish_mode(mode)
        return bool(launch_server)

    mode2 = _normalise_publish_mode(mode)

    if mode2 == "local":
        return True

    if mode2 == "remote":
        return False

    # mode="auto"
    return not (host is not None or port is not None)


def _normalise_remote_target(
    *,
    host: str | None,
    port: int | None,
) -> tuple[str, int]:
    return (
        str(host or "127.0.0.1"),
        int(port if port is not None else 8000),
    )


def _normalise_local_target(
    *,
    host: str | None,
    port: int | None,
) -> tuple[str, int]:
    return (
        str(host or "127.0.0.1"),
        int(port if port is not None else 8000),
    )


def _publish_view_local(
    obj: Any,
    *,
    host: str | None,
    port: int | None,
    label: str | None,
    section: str | None,
    view_id: str | None,
    kind: str | None,
    artifact_kind: str | None,
) -> None:
    """
    Publish directly into the in-process plotsrv server/store.

    The import is deliberately lazy to avoid import cycles.
    """
    from .server import refresh_view, start_server

    local_host, local_port = _normalise_local_target(host=host, port=port)

    start_server(
        host=local_host,
        port=local_port,
        auto_on_show=True,
        quiet=True,
        announce=True,
    )

    refresh_view(
        obj,
        label=label,
        section=section,
        view_id=view_id,
        kind=kind,
        artifact_kind=artifact_kind,
    )


def publish_view(
    obj: Any,
    *,
    launch_server: bool | None = None,
    mode: PublishMode | str | None = None,
    host: str | None = None,
    port: int | None = None,
    label: str | None = None,
    section: str | None = None,
    view_id: str | None = None,
    update_limit_s: int | None = None,
    force: bool = False,
    kind: str | None = None,
    artifact_kind: str | None = None,
) -> None:
    """
    Publish an object as a plotsrv browser view.

    Default behaviour is compatibility/auto mode:
      - host/port omitted  -> start/use an attached local server
      - host/port supplied -> publish over HTTP to an existing server

    Preferred explicit behaviour:
      - launch_server=True  -> start/use an attached local server
      - launch_server=False -> publish over HTTP to an existing server

    Legacy mode= is still accepted:
      - mode="local"  -> attached local server
      - mode="remote" -> HTTP publish
      - mode="auto"   -> compatibility/auto behaviour

    This accepts anything plotsrv knows how to display: plots, tables, text,
    JSON-like objects, markdown, HTML payloads, images, path-like files, and
    generic Python objects.
    """
    debug = _debug_enabled()

    try:
        launch = _resolve_launch_server(
            launch_server=launch_server,
            mode=mode,
            host=host,
            port=port,
        )
    except Exception:
        if debug:
            raise
        return

    remote_host, remote_port = _normalise_remote_target(host=host, port=port)

    if _try_publish_pathlike_view(
        obj,
        launch_server=launch,
        host=host if launch else remote_host,
        port=port if launch else remote_port,
        label=label,
        section=section,
        view_id=view_id,
        artifact_kind=artifact_kind,
        update_limit_s=update_limit_s,
        force=force,
        debug=debug,
    ):
        return

    if launch:
        try:
            _publish_view_local(
                obj,
                host=host,
                port=port,
                label=label,
                section=section,
                view_id=view_id,
                kind=kind,
                artifact_kind=artifact_kind,
            )
        except RuntimeError as e:
            if "plotsrv server already running" in str(e):
                raise
            if debug:
                raise
        except Exception:
            if debug:
                raise
        return

    if kind is None:
        if _is_dataframe(obj):
            kind2 = "table"
        elif _looks_like_plot(obj):
            kind2 = "plot"
        else:
            kind2 = "artifact"
    else:
        kind2 = str(kind).strip().lower()

    try:
        payload = _to_publish_payload(
            obj,
            kind=kind2,
            label=label,
            section=section,
            view_id=view_id,
            update_limit_s=update_limit_s,
            force=force,
            artifact_kind=artifact_kind,
        )
    except Exception:
        if debug:
            raise
        return

    _post_publish_payload(
        payload=payload,
        host=remote_host,
        port=remote_port,
        debug=debug,
    )
