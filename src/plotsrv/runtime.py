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
WatchMaterialization = Literal["memory", "file"]
WatchMaterializationRequest = Literal["auto", "memory", "file"]

_WATCH_MAX_BYTES_UNSET = object()


@dataclass(frozen=True, slots=True)
class RegisteredWatchView:
    path: Path
    view_id: str
    section: str
    label: str
    kind: Literal["artifact", "table"]
    read_mode: WatchReadMode
    materialization: WatchMaterialization = "memory"


@dataclass(frozen=True, slots=True)
class WatchPublishPayload:
    kind: Literal["artifact", "table"]
    artifact: Any = None
    artifact_kind: str | None = None
    table_df: Any = None


@dataclass(frozen=True, slots=True)
class FileBackedArtifactPreview:
    artifact: Any
    artifact_kind: str
    raw: bytes


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


def parse_watch_max_mb(raw: int | float | str | None) -> int | None:
    """
    Parse a watched-file MB limit from CLI/user input.

    Returns:
      - int bytes
      - None for off/no limit
    """
    if raw is None:
        return None

    if isinstance(raw, bool):
        return None if raw is False else 1024 * 1024

    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("off", "none", "null", "false", "no", "0", ""):
            return None

        try:
            mb = float(s)
        except Exception as e:
            raise ValueError(f"watch max MB must be a number or 'off': {raw!r}") from e

        if mb <= 0:
            return None

        return max(1, int(mb * 1024 * 1024))

    try:
        mb2 = float(raw)
    except Exception as e:
        raise ValueError(f"watch max MB must be a number or 'off': {raw!r}") from e

    if mb2 <= 0:
        return None

    return max(1, int(mb2 * 1024 * 1024))


def resolve_watch_cli_max_bytes(
    *,
    watch_max_bytes: int | str | None = None,
    watch_max_mb: int | float | str | None = None,
) -> int | None:
    """
    Resolve watched-file CLI size options.

    --watch-max-mb is preferred.
    --watch-max-bytes remains supported for compatibility/precision.
    """
    if watch_max_bytes is not None and watch_max_mb is not None:
        raise ValueError("Use only one of --watch-max-mb or --watch-max-bytes.")

    if watch_max_mb is not None:
        return parse_watch_max_mb(watch_max_mb)

    if watch_max_bytes is not None:
        return parse_watch_max_bytes(watch_max_bytes)

    return None


def coerce_watch_materialization_request(
    raw: str | None,
) -> WatchMaterializationRequest:
    """
    Coerce a watch materialisation request.

    Accepted values:
      - auto
      - memory
      - file

    Invalid/blank values fall back to the configured default.
    """
    if raw is None:
        return config.get_watch_materialization()

    value = str(raw).strip().lower()
    if value in ("auto", "memory", "file"):
        return value  # type: ignore[return-value]

    return config.get_watch_materialization()


def resolve_watch_materialization(
    path: str | Path,
    *,
    requested: str | None = None,
) -> WatchMaterialization:
    """
    Decide whether a watched file should be memory-backed or file-backed.

    This only decides the representation mode. It does not read the file and it
    does not register/update any store state.

    Rules:
      - memory -> memory
      - file   -> file
      - auto   -> file if file size is at/above the configured threshold,
                  otherwise memory

    If file size cannot be checked in auto mode, fall back to memory so existing
    watch behaviour remains conservative and backwards-compatible.
    """
    mode = coerce_watch_materialization_request(requested)

    if mode == "memory":
        return "memory"

    if mode == "file":
        return "file"

    threshold = config.get_watch_file_threshold_bytes()

    try:
        size = Path(path).expanduser().resolve().stat().st_size
    except Exception:
        return "memory"

    if int(size) >= int(threshold):
        return "file"

    return "memory"


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


def read_watch_file_bytes(
    path: str | Path,
    *,
    read_mode: WatchReadMode,
    max_bytes: int | None,
    watch_config: WatchConfig | None = None,
) -> bytes:
    """
    Read watched-file bytes using plotsrv's watch semantics.

    - CSV + tail keeps the header row.
    - head reads from the start.
    - tail reads from the end.
    - text-like tail reads are bounded by the useful render window.
    """
    p = Path(path).expanduser().resolve()
    fk = infer_file_kind(p)

    effective_max_bytes = get_effective_watch_read_max_bytes(
        p,
        read_mode=read_mode,
        max_bytes=max_bytes,
        watch_config=watch_config,
    )

    if fk == "csv" and read_mode == "tail":
        return read_csv_tail_with_header_bytes(p, max_bytes=effective_max_bytes)

    if read_mode == "head":
        return read_head_bytes(p, max_bytes=effective_max_bytes)

    return read_tail_bytes(p, max_bytes=effective_max_bytes)


def _min_enabled_limit(*limits: int | None) -> int | None:
    enabled = [x for x in limits if x is not None]
    if not enabled:
        return None
    return min(enabled)


def get_watch_tail_render_limit_for_path(
    path: str | Path,
    *,
    watch_config: WatchConfig | None = None,
) -> int | None:
    """
    Return the render limit that can safely bound tail reads for text-like files.

    CSV/table-like files are not controlled by render.text because CSV tail mode
    has special header-preserving behaviour and is later table-shaped.
    """
    p = Path(path).expanduser().resolve()
    kind = watch_config.kind if watch_config is not None else "auto"

    if kind == "json":
        return None

    if kind == "text":
        return get_watch_render_limit("text")

    if kind == "auto":
        fk = infer_file_kind(p)

        if fk == "csv":
            return None

        if fk == "html":
            return get_watch_render_limit("html")

        if fk == "markdown":
            return get_watch_render_limit("markdown")

        if fk == "json":
            return None

        return get_watch_render_limit("text")

    return get_watch_render_limit("text")


def get_effective_watch_read_max_bytes(
    path: str | Path,
    *,
    read_mode: WatchReadMode,
    max_bytes: int | None,
    watch_config: WatchConfig | None = None,
) -> int | None:
    """
    Return the number of bytes to read for a watched file.

    For tail mode on text-like files, there is no point reading substantially more
    than the render limit because C1 will truncate before publish anyway.

    Rules:
      watched_files.max_bytes=5_000_000 and render.text=1_000_000 -> 1_000_000
      watched_files.max_bytes=None and render.text=1_000_000      -> 1_000_000
      watched_files.max_bytes=5_000_000 and render.text=None      -> 5_000_000
      watched_files.max_bytes=None and render.text=None           -> None
    """
    if read_mode != "tail":
        return max_bytes

    render_limit = get_watch_tail_render_limit_for_path(
        path,
        watch_config=watch_config,
    )

    return _min_enabled_limit(max_bytes, render_limit)


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


def _watch_view_from_config(spec: WatchConfig) -> RegisteredWatchView:
    p = Path(spec.path).expanduser().resolve()
    section = (spec.section or "watch").strip() or "watch"
    label = (spec.label or p.name).strip() or p.name

    view_id = store.normalize_view_id(None, section=section, label=label)

    fk = infer_file_kind(p)
    read_mode: WatchReadMode = spec.read_mode or default_watch_read_mode(p)
    preregister_kind: Literal["artifact", "table"] = (
        "table" if fk == "csv" else "artifact"
    )
    materialization = resolve_watch_materialization(p)

    return RegisteredWatchView(
        path=p,
        view_id=view_id,
        section=section,
        label=label,
        kind=preregister_kind,
        read_mode=read_mode,
        materialization=materialization,
    )


def build_watched_file_meta(
    *,
    registered: RegisteredWatchView,
    spec: WatchConfig,
    materialization: WatchMaterialization,
    max_bytes: int | None,
    error: str | None = None,
) -> store.WatchedFileMeta:
    """
    Build watched-file metadata for a registered watch view.

    This is intentionally side-effect free. Later v0.5.0 steps can call this
    from registration or watch polling when file-backed views are introduced.
    """
    size_bytes: int | None = None
    mtime_ns: int | None = None

    try:
        st = registered.path.stat()
        size_bytes = int(st.st_size)
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    except Exception as e:
        if error is None:
            error = f"{type(e).__name__}: {e}"

    return store.WatchedFileMeta(
        view_id=registered.view_id,
        path=str(registered.path),
        file_kind=infer_file_kind(registered.path),
        read_mode=registered.read_mode,
        encoding=spec.encoding,
        materialization=materialization,
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
        max_bytes=max_bytes,
        last_checked_at=None,
        last_read_at=None,
        last_error=error,
    )


def register_watched_file_meta(
    *,
    registered: RegisteredWatchView,
    spec: WatchConfig,
) -> store.WatchedFileMeta:
    resolved_max_bytes = resolve_watch_max_bytes(spec, view_id=registered.view_id)
    meta = build_watched_file_meta(
        registered=registered,
        spec=spec,
        materialization=registered.materialization,
        max_bytes=resolved_max_bytes,
    )
    store.set_watched_file_meta(meta)
    return meta


def watch_config_from_meta(meta: store.WatchedFileMeta) -> WatchConfig:
    """
    Rebuild the watch config needed to preview a file-backed watched artifact.

    WatchedFileMeta stores the file/read details needed by app routes, but the
    existing watch payload builder expects WatchConfig. This helper keeps that
    conversion in one place.
    """
    kind: WatchKind = "auto"

    if meta.file_kind == "json":
        kind = "json"

    return WatchConfig(
        path=meta.path,
        label=None,
        section=None,
        kind=kind,
        read_mode=meta.read_mode,
        max_bytes=meta.max_bytes,
        encoding=meta.encoding,
    )


def read_file_backed_artifact_preview(
    meta: store.WatchedFileMeta,
) -> FileBackedArtifactPreview:
    """
    Read a bounded preview for a file-backed watched artifact.

    This is for artifact-like watched files only. CSV/table previews are handled
    separately in a later step.

    The helper:
      - reads only the effective watched preview window
      - preserves tail/head semantics
      - reuses existing watch coercion/render-limit behaviour
      - returns an artifact object and artifact kind ready for rendering
    """
    p = Path(meta.path).expanduser().resolve()

    if meta.file_kind == "csv":
        raise TypeError("file-backed CSV previews are table previews, not artifacts")

    if meta.file_kind == "image":
        raise TypeError("file-backed image previews are not supported yet")

    watch_config = watch_config_from_meta(meta)

    raw = read_watch_file_bytes(
        p,
        read_mode=meta.read_mode,
        max_bytes=meta.max_bytes,
        watch_config=watch_config,
    )

    payload = build_watch_publish_payload(
        path=p,
        raw=raw,
        watch_config=watch_config,
        read_mode=meta.read_mode,
        max_bytes=meta.max_bytes,
        max_rows=config.get_table_truncate_rows(),
        max_columns=config.get_table_truncate_columns(),
    )

    if payload.kind != "artifact":
        raise TypeError(
            f"file-backed artifact preview expected artifact payload, got {payload.kind!r}"
        )

    return FileBackedArtifactPreview(
        artifact=payload.artifact,
        artifact_kind=payload.artifact_kind or "text",
        raw=raw,
    )


def register_watch_views(
    watches: Sequence[WatchConfig | Mapping[str, Any]],
    *,
    activate_first_if_none: bool = True,
) -> list[RegisteredWatchView]:
    """
    Register watched files as real plotsrv views.

    This makes watch-only workflows first-class: the UI can show a watched file
    view before any Python object has been published and before the watcher has
    emitted its first payload.
    """
    configs = coerce_watch_configs(watches)
    registered = [_watch_view_from_config(spec) for spec in configs]

    active_before = store.get_active_view_id()

    for spec, view in zip(configs, registered, strict=True):
        store.register_view(
            view_id=view.view_id,
            section=view.section,
            label=view.label,
            kind=view.kind,
            activate_if_first=False,
        )

        register_watched_file_meta(registered=view, spec=spec)

    if activate_first_if_none and registered and active_before is None:
        store.set_active_view(registered[0].view_id)

    return registered


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


def _normalise_render_limit(raw: Any) -> int | None:
    """
    Convert render limit values to an int or None.

    None means no render truncation. This accepts the same broad shape as the
    existing config layer: int-like values, "off", "none", "false", etc.
    """
    if raw is None:
        return None

    if raw is settings._TRUNCATE_OFF:
        return None

    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("off", "none", "null", "false", "no", "0", ""):
            return None
        try:
            return max(1, int(float(s)))
        except Exception:
            return None

    try:
        return max(1, int(raw))
    except Exception:
        return None


def get_watch_render_limit(artifact_kind: str | None) -> int | None:
    """
    Return the render limit that should be applied to a watched text-like artifact.

    C1 deliberately uses the existing render limits, not publish-limits.
    """
    ak = (artifact_kind or "text").strip().lower()

    if ak in {"watch_error", "publish_error"}:
        return None

    if ak == "markdown":
        return _normalise_render_limit(config.get_render_markdown_max_chars())

    if ak == "html":
        return _normalise_render_limit(config.get_render_html_max_chars())

    return _normalise_render_limit(config.get_render_text_max_chars())


def truncate_watch_text_like_artifact(
    artifact: Any,
    *,
    artifact_kind: str | None,
) -> Any:
    """
    Apply watched-file render limits before POSTing to /publish.

    Only text-like watched artifacts are affected:
      - text
      - markdown
      - html

    JSON objects and tables are left unchanged.
    """
    ak = (artifact_kind or "text").strip().lower()

    if ak in {"watch_error", "publish_error"}:
        return artifact

    if ak not in {"text", "markdown", "html"}:
        return artifact

    if not isinstance(artifact, str):
        return artifact

    limit = get_watch_render_limit(ak)
    if limit is None:
        return artifact

    if len(artifact) <= limit:
        return artifact

    omitted = len(artifact) - limit
    return (
        artifact[:limit]
        + "\n\n"
        + f"[plotsrv watch] truncated {omitted} characters using limits.truncate_after.{ak}"
    )


def build_watch_publish_payload(
    *,
    path: str | Path,
    raw: bytes,
    watch_config: WatchConfig,
    read_mode: WatchReadMode,
    max_bytes: int | None,
    max_rows: int | None = None,
    max_columns: int | None = None,
) -> WatchPublishPayload:
    """
    Convert watched-file bytes into a prepared publish payload.

    This centralises the text/json/auto branching so standalone CLI watch mode
    and background watch threads prepare watched files in the same way.
    """
    p = Path(path).expanduser().resolve()
    rows_limit = config.get_table_truncate_rows() if max_rows is None else max_rows
    columns_limit = (
        config.get_table_truncate_columns() if max_columns is None else max_columns
    )

    if watch_config.kind == "text":
        txt = raw.decode(watch_config.encoding, errors="replace")
        artifact = with_text_anchor_header(txt, read_mode)
        artifact = truncate_watch_text_like_artifact(
            artifact,
            artifact_kind="text",
        )

        return WatchPublishPayload(
            kind="artifact",
            artifact=artifact,
            artifact_kind="text",
        )

    if watch_config.kind == "json":
        txt = raw.decode(watch_config.encoding, errors="replace")
        try:
            obj = json.loads(txt)
            return WatchPublishPayload(
                kind="artifact",
                artifact=obj,
                artifact_kind="json",
            )
        except Exception as e:
            artifact = (
                f"[plotsrv watch] JSON parse error: "
                f"{type(e).__name__}: {e}\n\n{txt}"
            )

            return WatchPublishPayload(
                kind="artifact",
                artifact=artifact,
                artifact_kind="watch_error",
            )

    try:
        coerced = coerce_file_to_publishable(
            p,
            encoding=watch_config.encoding,
            max_bytes=max_bytes,
            max_rows=rows_limit,
            max_columns=columns_limit,
            raw=raw,
        )

        if coerced.publish_kind == "table":
            return WatchPublishPayload(
                kind="table",
                table_df=coerced.obj,
            )

        obj_to_publish = coerced.obj
        artifact_kind = coerced.artifact_kind or "text"

        if artifact_kind == "text":
            obj_to_publish = with_text_anchor_header(str(coerced.obj), read_mode)

        obj_to_publish = truncate_watch_text_like_artifact(
            obj_to_publish,
            artifact_kind=artifact_kind,
        )

        return WatchPublishPayload(
            kind="artifact",
            artifact=obj_to_publish,
            artifact_kind=artifact_kind,
        )

    except Exception as e:
        txt = raw.decode(watch_config.encoding, errors="replace")
        artifact = f"[plotsrv watch] parse error: {type(e).__name__}: {e}\n\n{txt}"

        return WatchPublishPayload(
            kind="artifact",
            artifact=artifact,
            artifact_kind="watch_error",
        )


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


def get_watch_adjustment_keys(
    *,
    path: str | Path | None,
    artifact_kind: str | None,
) -> list[str]:
    """
    Return config keys likely to help with a failed watched-file publish.
    """
    ak = (artifact_kind or "text").strip().lower()

    if path is not None:
        try:
            fk = infer_file_kind(Path(path).expanduser().resolve())
        except Exception:
            fk = None

        if fk == "csv":
            return [
                "limits.watched_files.max_mb",
                "limits.truncate_after.table_rows",
                "limits.truncate_after.table_columns",
            ]

        if fk == "markdown":
            return [
                "limits.watched_files.max_mb",
                "limits.truncate_after.markdown",
            ]

        if fk == "html":
            return [
                "limits.watched_files.max_mb",
                "limits.truncate_after.html",
            ]

        if ak == "markdown":
            return [
                "limits.watched_files.max_mb",
                "limits.truncate_after.markdown",
            ]

        if ak == "html":
            return [
                "limits.watched_files.max_mb",
                "limits.truncate_after.html",
            ]

    return [
        "limits.watched_files.max_mb",
        "limits.truncate_after.text",
    ]


def build_watch_publish_error_artifact(
    *,
    error: BaseException | str,
    path: str | Path | None,
    section: str,
    label: str,
    artifact_kind: str | None,
    read_mode: WatchReadMode | None = None,
) -> str:
    """
    Build a user-visible watch publish failure message.

    This is intentionally plain text so it can render even when richer artifact
    rendering is the thing that failed.
    """
    if isinstance(error, BaseException):
        error_text = f"{type(error).__name__}: {error}"
    else:
        error_text = str(error)

    file_text = (
        str(Path(path).expanduser().resolve()) if path is not None else "unknown"
    )
    keys = get_watch_adjustment_keys(path=path, artifact_kind=artifact_kind)

    key_lines = "\n".join(f"  - {key}" for key in keys)

    tail_hint = ""
    if read_mode != "tail":
        tail_hint = (
            "\n\n"
            "For large logs or text files, prefer tail mode:\n"
            "  plotsrv watch <file> --watch-tail\n"
            "  plotsrv run <target> --watch <file> --watch-tail"
        )

    return (
        "[plotsrv watch] publish failed\n\n"
        "What failed:\n"
        f"  {error_text}\n\n"
        "Watched file:\n"
        f"  {file_text}\n\n"
        "View:\n"
        f"  section={section!r}, label={label!r}\n\n"
        "Config keys to adjust:\n"
        f"{key_lines}"
        f"{tail_hint}"
    )


def publish_prepared_watch_payload(
    *,
    host: str,
    port: int,
    label: str,
    section: str,
    payload: WatchPublishPayload,
    update_limit_s: int | None = None,
    force: bool = False,
    path: str | Path | None = None,
    read_mode: WatchReadMode | None = None,
) -> bool:
    try:
        ok = publish_watch_payload(
            host=host,
            port=port,
            label=label,
            section=section,
            kind=payload.kind,
            artifact=payload.artifact,
            artifact_kind=payload.artifact_kind,
            table_df=payload.table_df,
            update_limit_s=update_limit_s,
            force=force,
        )
    except Exception as e:
        ok = False
        error: BaseException | str = e
    else:
        error = "server rejected or did not accept the watch publish"

    if ok:
        return True

    fallback = build_watch_publish_error_artifact(
        error=error,
        path=path,
        section=section,
        label=label,
        artifact_kind=payload.artifact_kind,
        read_mode=read_mode,
    )

    try:
        return publish_watch_payload(
            host=host,
            port=port,
            label=label,
            section=section,
            kind="artifact",
            artifact=fallback,
            artifact_kind="watch_error",
            update_limit_s=None,
            force=True,
        )
    except Exception:
        return False


def start_watch_threads(
    watches: Sequence[WatchConfig | Mapping[str, Any]],
    *,
    host: str,
    port: int,
    register_views: bool = True,
) -> list[threading.Thread]:
    configs = coerce_watch_configs(watches)
    threads: list[threading.Thread] = []

    if register_views:
        registered_views = register_watch_views(configs, activate_first_if_none=True)
    else:
        registered_views = [_watch_view_from_config(spec) for spec in configs]

    for spec, registered in zip(configs, registered_views, strict=True):
        p = registered.path
        section = registered.section
        label = registered.label
        view_id = registered.view_id
        read_mode = registered.read_mode
        resolved_max_bytes = resolve_watch_max_bytes(spec, view_id=view_id)

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
                    raw = read_watch_file_bytes(
                        pth,
                        read_mode=watch_read_mode,
                        max_bytes=watch_max_bytes,
                        watch_config=watch_config,
                    )
                except Exception as e:

                    publish_watch_payload(
                        host=host,
                        port=port,
                        label=view_label,
                        section=view_section,
                        kind="artifact",
                        artifact=f"[plotsrv watch] read error: {type(e).__name__}: {e}",
                        artifact_kind="watch_error",
                        update_limit_s=watch_config.update_limit_s,
                        force=watch_config.force,
                    )
                    time.sleep(1.0)
                    continue

                last_sig = sig

                payload = build_watch_publish_payload(
                    path=pth,
                    raw=raw,
                    watch_config=watch_config,
                    read_mode=watch_read_mode,
                    max_bytes=watch_max_bytes,
                    max_rows=config.get_table_truncate_rows(),
                    max_columns=config.get_table_truncate_columns(),
                )

                publish_prepared_watch_payload(
                    host=host,
                    port=port,
                    label=view_label,
                    section=view_section,
                    payload=payload,
                    update_limit_s=watch_config.update_limit_s,
                    force=watch_config.force,
                    path=pth,
                    read_mode=watch_read_mode,
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
