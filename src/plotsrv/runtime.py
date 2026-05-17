# src/plotsrv/runtime.py
from __future__ import annotations

import json
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from collections.abc import Mapping, Sequence

from . import config, settings, store
from .file_kinds import coerce_file_to_publishable, infer_file_kind

WatchReadMode = Literal["head", "tail"]
WatchKind = Literal["auto", "text", "json"]

_WATCH_MAX_BYTES_UNSET = object()


@dataclass(frozen=True, slots=True)
class WatchConfig:
    path: str | Path
    label: str | None = None
    section: str | None = None
    kind: WatchKind = "auto"
    read_mode: WatchReadMode | None = None
    max_bytes: int | None | object = _WATCH_MAX_BYTES_UNSET
    encoding: str = "utf-8"
    update_limit_s: int | None = None
    force: bool = False


def parse_truncate_arg(raw: int | str | None, *, no_truncate: bool) -> object:
    """
    Parse CLI/Python render truncation override.

    Returns one of:
      - settings._UNSET
      - settings._TRUNCATE_OFF
      - int max chars
    """
    if no_truncate:
        return settings._TRUNCATE_OFF

    if raw is None:
        return settings._UNSET

    s = str(raw).strip().lower()
    if s in ("off", "none", "false", "no", "0"):
        return settings._TRUNCATE_OFF

    try:
        n = int(float(s))
        return max(1, n)
    except Exception:
        return settings._UNSET


def parse_watch_max_bytes(raw: int | str | bool | None) -> int | None:
    """
    Parse watched-file read limit.

    Returns:
      - int => read at most this many bytes
      - None => read whole file
    """
    if raw is None:
        return config.get_watch_max_bytes()

    if isinstance(raw, bool):
        return config.get_watch_max_bytes() if raw else None

    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("off", "none", "null", "false", "no", "0", ""):
            return None
        try:
            n = int(float(s))
            if n < 1:
                return config.get_watch_max_bytes()
            return n
        except Exception:
            raise ValueError(
                f"watch max bytes must be an integer or 'off', got {raw!r}"
            )

    try:
        n2 = int(raw)
        if n2 < 1:
            return config.get_watch_max_bytes()
        return n2
    except Exception:
        raise ValueError(f"watch max bytes must be an integer or 'off', got {raw!r}")


def apply_runtime_options(
    *,
    config_path: str | Path | None = None,
    config: str | Path | None = None,
    name: str | None = None,
    truncate: int | str | None = None,
    no_truncate: bool = False,
) -> None:
    """
    Apply runtime options shared by CLI and Python API.

    `config` is accepted for the public Python API.
    `config_path` is accepted for internal/CLI clarity.
    """
    cfg = config_path if config_path is not None else config

    if cfg is not None:
        settings.set_runtime_context(config_path=cfg)

    if name is not None:
        settings.set_runtime_context(name=name)

    truncate_override = parse_truncate_arg(truncate, no_truncate=no_truncate)
    if truncate_override is not settings._UNSET:
        settings.set_runtime_context(truncate_override=truncate_override)


def coerce_watch_config(value: WatchConfig | Mapping[str, Any]) -> WatchConfig:
    if isinstance(value, WatchConfig):
        return value

    if not isinstance(value, Mapping):
        raise TypeError(
            "watch config must be WatchConfig or mapping, " f"got {type(value)!r}"
        )

    if "path" not in value:
        raise ValueError("watch config requires 'path'")

    raw_kind = str(value.get("kind", "auto")).strip().lower() or "auto"
    if raw_kind not in ("auto", "text", "json"):
        raise ValueError(
            f"watch kind must be 'auto', 'text', or 'json', got {raw_kind!r}"
        )

    raw_read_mode = value.get("read_mode", None)
    read_mode: WatchReadMode | None
    if raw_read_mode is None or str(raw_read_mode).strip() == "":
        read_mode = None
    else:
        rm = str(raw_read_mode).strip().lower()
        if rm not in ("head", "tail"):
            raise ValueError(f"watch read_mode must be 'head' or 'tail', got {rm!r}")
        read_mode = rm  # type: ignore[assignment]

    max_bytes: int | None | object
    if "max_bytes" in value:
        max_bytes = parse_watch_max_bytes(value.get("max_bytes"))
    else:
        max_bytes = _WATCH_MAX_BYTES_UNSET

    return WatchConfig(
        path=value["path"],  # type: ignore[arg-type]
        label=(None if value.get("label") is None else str(value.get("label"))),
        section=(None if value.get("section") is None else str(value.get("section"))),
        kind=raw_kind,  # type: ignore[arg-type]
        read_mode=read_mode,
        max_bytes=max_bytes,
        encoding=str(value.get("encoding", "utf-8")),
        update_limit_s=(
            None
            if value.get("update_limit_s") is None
            else int(value.get("update_limit_s"))
        ),
        force=bool(value.get("force", False)),
    )


def coerce_watch_configs(
    watches: Sequence[WatchConfig | Mapping[str, Any]] | None,
) -> list[WatchConfig]:
    if not watches:
        return []
    return [coerce_watch_config(w) for w in watches]


def resolve_watch_max_bytes(
    spec: WatchConfig,
    *,
    view_id: str,
) -> int | None:
    """
    Resolve the effective watched-file read limit.

    Resolution:
      - WatchConfig(max_bytes=<int>) => explicit byte cap
      - WatchConfig(max_bytes=None) => explicit full-file read
      - WatchConfig(max_bytes unset) => global config/default

    Note:
      view_id is accepted for future extension, but watched-file input limits are
      currently global only.
    """
    if spec.max_bytes is _WATCH_MAX_BYTES_UNSET:
        return config.get_watch_max_bytes()

    return spec.max_bytes  # type: ignore[return-value]


def default_watch_read_mode(path: Path) -> WatchReadMode:
    fk = infer_file_kind(path)

    if fk in {
        "csv",
        "json",
        "yaml",
        "toml",
        "ini",
        "markdown",
        "html",
        "image",
    }:
        return "head"

    return "tail"


def with_text_anchor_header(text: str, anchor: WatchReadMode) -> str:
    if anchor != "tail":
        return text
    return "\ufeffPLOTSRV_ANCHOR=tail\n" + text


def _drop_first_partial_line(raw: bytes) -> bytes:
    """
    Drop the first line from a tail chunk when it may be partial.

    If doing so would remove everything useful, keep the original chunk.
    """
    if not raw:
        return raw

    nl = raw.find(b"\n")
    if nl == -1:
        return raw

    out = raw[nl + 1 :]
    return out or raw


def _drop_last_partial_line(raw: bytes) -> bytes:
    """
    Drop the final line from a head chunk when it may be partial.

    If doing so would remove everything useful, keep the original chunk.
    """
    if not raw:
        return raw

    if raw.endswith((b"\n", b"\r\n")):
        return raw

    nl = raw.rfind(b"\n")
    if nl == -1:
        return raw

    out = raw[: nl + 1]
    return out or raw


def read_tail_bytes(p: Path, *, max_bytes: int | None) -> bytes:
    if max_bytes is None:
        return p.read_bytes()

    max_bytes = max(1, int(max_bytes))

    with p.open("rb") as f:
        try:
            f.seek(0, 2)  # os.SEEK_END without importing os
            size = f.tell()
            start = max(0, size - max_bytes)
            f.seek(start, 0)
            raw = f.read(max_bytes)
        except Exception:
            f.seek(0)
            start = 0
            raw = f.read(max_bytes)

    if start > 0:
        return _drop_first_partial_line(raw)

    return raw


def read_head_bytes(p: Path, *, max_bytes: int | None) -> bytes:
    if max_bytes is None:
        return p.read_bytes()

    max_bytes = max(1, int(max_bytes))

    with p.open("rb") as f:
        raw = f.read(max_bytes)
        try:
            more = bool(f.read(1))
        except Exception:
            more = False

    if more:
        return _drop_last_partial_line(raw)

    return raw


def read_csv_tail_with_header_bytes(p: Path, *, max_bytes: int | None) -> bytes:
    if max_bytes is None:
        return p.read_bytes()

    max_bytes = max(1, int(max_bytes))

    header = b""
    with p.open("rb") as f:
        chunk = f.read(min(64_000, max_bytes))
        nl = chunk.find(b"\n")
        header = chunk if nl == -1 else chunk[: nl + 1]

    tail = read_tail_bytes(p, max_bytes=max_bytes)

    if tail.startswith(header) or tail == header:
        return tail

    if header and not header.endswith(b"\n"):
        header = header + b"\n"

    return header + tail


def post_publish_payload(*, host: str, port: int, payload: dict[str, Any]) -> bool:
    url = f"http://{host}:{port}/publish"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            _ = resp.read()
        return True
    except Exception:
        return False


def publish_watch_payload(
    *,
    host: str,
    port: int,
    label: str,
    section: str,
    kind: str,
    artifact: Any = None,
    artifact_kind: str | None = None,
    table_df: Any = None,
    update_limit_s: int | None = None,
    force: bool = False,
) -> bool:
    payload: dict[str, Any] = {
        "kind": kind,
        "label": label,
        "section": section,
        "update_limit_s": update_limit_s,
        "force": force,
        "publish_source": "watch",
    }

    if kind == "artifact":
        payload["artifact"] = artifact
        payload["artifact_kind"] = artifact_kind or "text"

    elif kind == "table":
        import pandas as pd

        if not isinstance(table_df, pd.DataFrame):
            raise TypeError("watch table publish expected pandas DataFrame")

        payload["table"] = {
            "columns": list(table_df.columns),
            "rows": table_df.to_dict(orient="records"),
            "total_rows": len(table_df),
            "returned_rows": len(table_df),
        }
        payload["table_html_simple"] = None

    else:
        raise ValueError(f"Unsupported watch publish kind: {kind!r}")

    return post_publish_payload(host=host, port=port, payload=payload)


def start_watch_threads(
    watches: Sequence[WatchConfig | Mapping[str, Any]],
    *,
    host: str,
    port: int,
) -> list[threading.Thread]:
    configs = coerce_watch_configs(watches)
    threads: list[threading.Thread] = []

    for spec in configs:
        p = Path(spec.path).expanduser().resolve()
        section = (spec.section or "watch").strip() or "watch"
        label = (spec.label or p.name).strip() or p.name

        view_id = store.normalize_view_id(None, section=section, label=label)

        fk = infer_file_kind(p)
        read_mode: WatchReadMode = spec.read_mode or default_watch_read_mode(p)
        preregister_kind = "table" if fk == "csv" else "artifact"
        resolved_max_bytes = resolve_watch_max_bytes(spec, view_id=view_id)

        store.register_view(
            view_id=view_id,
            section=section,
            label=label,
            kind=preregister_kind,
            activate_if_first=False,
        )

        def _worker(
            pth: Path = p,
            view_label: str = label,
            view_section: str = section,
            watch_config: WatchConfig = spec,
            watch_read_mode: WatchReadMode = read_mode,
            watch_max_bytes: int | None = resolved_max_bytes,
        ) -> None:
            last_sig: tuple[int, int] | None = None

            while True:
                try:
                    st = pth.stat()
                    sig = (
                        int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                        int(st.st_size),
                    )
                except Exception:
                    sig = None

                if sig is not None and sig == last_sig:
                    time.sleep(1.0)
                    continue

                try:
                    fk2 = infer_file_kind(pth)
                    if fk2 == "csv" and watch_read_mode == "tail":
                        raw = read_csv_tail_with_header_bytes(
                            pth, max_bytes=watch_max_bytes
                        )
                    elif watch_read_mode == "head":
                        raw = read_head_bytes(pth, max_bytes=watch_max_bytes)
                    else:
                        raw = read_tail_bytes(pth, max_bytes=watch_max_bytes)
                except Exception as e:
                    publish_watch_payload(
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        kind="artifact",
                        artifact=f"[plotsrv watch] read error: {type(e).__name__}: {e}",
                        artifact_kind="text",
                        update_limit_s=watch_config.update_limit_s,
                        force=watch_config.force,
                    )
                    time.sleep(1.0)
                    continue

                last_sig = sig

                if watch_config.kind == "text":
                    txt = raw.decode(watch_config.encoding, errors="replace")
                    txt2 = with_text_anchor_header(txt, watch_read_mode)
                    publish_watch_payload(
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        kind="artifact",
                        artifact=txt2,
                        artifact_kind="text",
                        update_limit_s=watch_config.update_limit_s,
                        force=watch_config.force,
                    )
                    time.sleep(1.0)
                    continue

                if watch_config.kind == "json":
                    try:
                        txt = raw.decode(watch_config.encoding, errors="replace")
                        obj = json.loads(txt)
                        publish_watch_payload(
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            kind="artifact",
                            artifact=obj,
                            artifact_kind="json",
                            update_limit_s=watch_config.update_limit_s,
                            force=watch_config.force,
                        )
                    except Exception as e:
                        txt = raw.decode(watch_config.encoding, errors="replace")
                        publish_watch_payload(
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            kind="artifact",
                            artifact=f"[plotsrv watch] JSON parse error: {type(e).__name__}: {e}\n\n{txt}",
                            artifact_kind="text",
                            update_limit_s=watch_config.update_limit_s,
                            force=watch_config.force,
                        )
                    time.sleep(1.0)
                    continue

                try:
                    coerced = coerce_file_to_publishable(
                        pth,
                        encoding=watch_config.encoding,
                        max_bytes=watch_max_bytes,
                        max_rows=config.get_max_table_rows_rich(),
                        raw=raw,
                    )

                    if coerced.publish_kind == "table":
                        publish_watch_payload(
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            kind="table",
                            table_df=coerced.obj,
                            update_limit_s=watch_config.update_limit_s,
                            force=watch_config.force,
                        )
                    else:
                        obj_to_publish = coerced.obj
                        ak = coerced.artifact_kind or "text"

                        if ak == "text":
                            obj_to_publish = with_text_anchor_header(
                                str(coerced.obj), watch_read_mode
                            )

                        publish_watch_payload(
                            host=host,
                            port=port,
                            label=view_label,
                            section=view_section,
                            kind="artifact",
                            artifact=obj_to_publish,
                            artifact_kind=ak,
                            update_limit_s=watch_config.update_limit_s,
                            force=watch_config.force,
                        )
                except Exception as e:
                    txt = raw.decode(watch_config.encoding, errors="replace")
                    publish_watch_payload(
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        kind="artifact",
                        artifact=f"[plotsrv watch] parse error: {type(e).__name__}: {e}\n\n{txt}",
                        artifact_kind="text",
                        update_limit_s=watch_config.update_limit_s,
                        force=watch_config.force,
                    )

                time.sleep(1.0)

        t = threading.Thread(
            target=_worker,
            name=f"plotsrv-watch:{p.name}",
            daemon=True,
        )
        t.start()
        threads.append(t)

    return threads
