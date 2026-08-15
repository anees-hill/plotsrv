# src/plotsrv/store.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
import threading
from typing import Any, Callable, Literal

import pandas as pd
from . import config
from .artifacts import Artifact, ArtifactKind, Truncation

IconKey = Literal[
    "unknown",
    "plot",
    "table",
    "text",
    "json",
    "python",
    "markdown",
    "image",
    "html",
    "traceback",
    "exception",  # legacy alias
]


@dataclass(frozen=True, slots=True)
class ViewMeta:
    """
    Metadata that describes a view shown in the UI dropdown.
    """

    view_id: str
    kind: str  # "none" | "plot" | "table" | "artifact"
    label: str
    section: str | None = None

    icon_key: IconKey = "unknown"


@dataclass(slots=True)
class ViewState:
    """
    Per-view state that the UI can display.

    Each view is independent: plot/table/status.
    """

    kind: str = "none"  # "none" | "plot" | "table"
    icon_key: IconKey = "unknown"
    plot_png: bytes | None = None
    table_df: pd.DataFrame | None = None
    table_html_simple: str | None = None
    status: dict[str, Any] = None  # populated in __post_init__
    table_total_rows: int | None = None
    table_returned_rows: int | None = None
    artifact: Artifact | None = None
    watched_file: WatchedFileMeta | None = None
    render_revision: int = 0

    # publish throttling
    last_publish_at: float | None = None  # epoch seconds

    def __post_init__(self) -> None:
        if self.status is None:
            self.status = {
                "last_updated": None,
                "last_duration_s": None,
                "last_error": None,
                "publish_source": "normal",
                "restored_from_storage": False,
                "restored_at": None,
                "restore_source": None,
            }


@dataclass(frozen=True, slots=True)
class WatchedFileMeta:
    """
    Metadata for a watched file view.

    This lets plotsrv represent a watched file without necessarily keeping the
    full file contents in memory. v0.5.0 starts by storing this metadata only;
    later steps will use it to serve file-backed previews on demand.
    """

    view_id: str
    path: str
    file_kind: str
    read_mode: Literal["head", "tail"]
    encoding: str
    materialization: Literal["memory", "file"]
    size_bytes: int | None = None
    mtime_ns: int | None = None
    max_bytes: int | None = None
    last_checked_at: str | None = None
    last_read_at: str | None = None
    last_error: str | None = None


def _icon_for_view_kind(
    kind: str, *, artifact_kind: ArtifactKind | None = None
) -> IconKey:
    k = (kind or "none").strip().lower()

    if k == "plot":
        return "plot"
    if k == "table":
        return "table"

    if k == "artifact":
        ak = (artifact_kind or "python").strip().lower()

        if ak in ("text", "json", "python", "markdown", "image", "html"):
            return ak  # type: ignore[return-value]

        if ak in ("traceback", "exception"):
            return "traceback"

        return "python"

    return "unknown"


def _icon_for_watched_file_kind(file_kind: str) -> IconKey:
    fk = (file_kind or "unknown").strip().lower()

    if fk == "csv":
        return "table"

    if fk == "json":
        return "json"

    if fk == "markdown":
        return "markdown"

    if fk == "html":
        return "html"

    if fk == "image":
        return "image"

    return "text"


# Global store: multi-view

_VIEWS: dict[str, ViewState] = {}
_VIEW_META: dict[str, ViewMeta] = {}

_ACTIVE_VIEW_ID: str = "default"

# ---- Service mode / CLI RunnerService info -----------------------------------

_SERVICE_INFO: dict[str, Any] = {
    "service_mode": False,
    "service_target": None,
    "service_refresh_rate_s": None,
}

_SERVICE_STOP_HOOK: Callable[[], None] | None = None

# The FastAPI request handlers and PublishWorker can both touch the module-level
# store. Keep each API operation atomic; RLock permits the existing public
# helpers to call one another without changing their shape.
_STORE_LOCK = threading.RLock()

# Rendered HTML is cached by this state token rather than by payload identity.
# A process-wide monotonic counter keeps a reset-and-republish cycle from ever
# reusing an earlier view revision.
_RENDER_REVISION_COUNTER = 0

# The browser receives a complete view-selector snapshot in its initial page.
# It only needs to request that comparatively large payload again when a menu
# entry changes, rather than for every published value in an existing view.
_VIEW_MENU_REVISION = 0


# Helpers


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_publish_source(publish_source: str | None) -> str:
    raw = str(publish_source or "normal").strip().lower()
    return "watch" if raw == "watch" else "normal"


def _ensure_view(view_id: str) -> ViewState:
    if view_id not in _VIEWS:
        _VIEWS[view_id] = ViewState()
    return _VIEWS[view_id]


def _touch_render_revision(st: ViewState) -> None:
    global _RENDER_REVISION_COUNTER
    _RENDER_REVISION_COUNTER += 1
    st.render_revision = _RENDER_REVISION_COUNTER


def _touch_view_menu_revision() -> None:
    global _VIEW_MENU_REVISION
    _VIEW_MENU_REVISION += 1


def normalize_view_id(
    view_id: str | None, *, section: str | None = None, label: str | None = None
) -> str:
    """
    Normalize incoming view identifiers.

    - If explicit view_id supplied: use it.
    - Otherwise: create view_id from section/label.
    """
    if view_id:
        return str(view_id)

    sec = (section or "default").strip() or "default"
    lab = (label or "default").strip() or "default"
    return f"{sec}:{lab}"


# View registry API


def register_view(
    *,
    view_id: str | None = None,
    section: str | None = None,
    label: str | None = None,
    kind: str = "none",
    icon_key: IconKey | None = None,  # NEW
    activate_if_first: bool = True,
) -> str:
    vid = normalize_view_id(view_id, section=section, label=label)
    st = _ensure_view(vid)

    # allow upgrade of assigned view dropdown menu icon
    if kind in ("plot", "table", "artifact"):
        st.kind = kind

    if icon_key is not None:
        st.icon_key = icon_key

    previous_meta = _VIEW_META.get(vid)
    next_meta = ViewMeta(
        view_id=vid,
        kind=st.kind,
        label=label or (previous_meta.label if previous_meta else vid),
        section=(
            section
            if section is not None
            else (previous_meta.section if previous_meta else None)
        ),
        icon_key=st.icon_key,
    )
    _VIEW_META[vid] = next_meta
    if next_meta != previous_meta:
        _touch_view_menu_revision()

    global _ACTIVE_VIEW_ID
    if (
        activate_if_first
        and (_ACTIVE_VIEW_ID is None or _ACTIVE_VIEW_ID == "default")
        and len(_VIEW_META) == 1
    ):
        _ACTIVE_VIEW_ID = vid

    return vid


def list_views() -> list[ViewMeta]:
    """
    Return UI-ready view metadata.

    Ordering rules:
      - sections listed in config come first, in order
      - remaining sections come afterwards alphabetically
      - labels.<section> listed come first within that section, in order
      - remaining labels come afterwards alphabetically
    """
    metas = list(_VIEW_META.values())

    # Pull in optional configured order
    section_order = config.get_view_order_sections()  # list[str] | None

    section_rank: dict[str, int] = {}
    if section_order:
        for i, s in enumerate(section_order):
            section_rank[s] = i

    def _section_sort_key(sec: str) -> tuple[int, str]:
        # (0, rank) for configured sections, else (1, alpha)
        if sec in section_rank:
            return (0, f"{section_rank[sec]:09d}")
        return (1, sec.lower())

    # Pre-fetch label ranking maps for sections that have them
    label_rank_by_section: dict[str, dict[str, int]] = {}
    for m in metas:
        sec = (m.section or "default").strip() or "default"
        if sec in label_rank_by_section:
            continue
        order = config.get_view_order_labels(sec)
        if order:
            label_rank_by_section[sec] = {lab: i for i, lab in enumerate(order)}

    def _label_sort_key(sec: str, label: str) -> tuple[int, str]:
        ranks = label_rank_by_section.get(sec)
        if ranks and label in ranks:
            return (0, f"{ranks[label]:09d}")
        return (1, label.lower())

    def _key(m: ViewMeta) -> tuple[tuple[int, str], tuple[int, str]]:
        sec = (m.section or "default").strip() or "default"
        return (_section_sort_key(sec), _label_sort_key(sec, m.label))

    return sorted(metas, key=_key)


def set_active_view(view_id: str) -> None:
    global _ACTIVE_VIEW_ID
    _ACTIVE_VIEW_ID = view_id
    _ensure_view(view_id)


def get_active_view_id() -> str:
    return _ACTIVE_VIEW_ID


def get_view_menu_revision() -> int:
    """Return the change token for browser view-selector metadata."""
    return _VIEW_MENU_REVISION


def get_view_state(view_id: str | None = None) -> ViewState:
    vid = view_id or _ACTIVE_VIEW_ID
    return _ensure_view(vid)


def get_render_revision(*, view_id: str | None = None) -> int:
    """Return the display-state revision used by the rendered-artifact cache."""
    return get_view_state(view_id).render_revision


# Watched-file metadata API


def set_watched_file_meta(meta: WatchedFileMeta) -> None:
    """
    Attach watched-file metadata to a view.

    This does not publish file contents. It only records how the watched view is
    backed so routes/runtime code can decide whether to read from memory or file.
    """
    st = get_view_state(meta.view_id)
    st.watched_file = meta
    _touch_render_revision(st)

    if st.icon_key == "unknown":
        st.icon_key = _icon_for_watched_file_kind(meta.file_kind)

    if meta.view_id in _VIEW_META:
        existing = _VIEW_META[meta.view_id]
        next_meta = ViewMeta(
            view_id=existing.view_id,
            kind=existing.kind,
            label=existing.label,
            section=existing.section,
            icon_key=st.icon_key,
        )
        _VIEW_META[meta.view_id] = next_meta
        if next_meta != existing:
            _touch_view_menu_revision()


def has_watched_file_meta(*, view_id: str | None = None) -> bool:
    st = get_view_state(view_id)
    return st.watched_file is not None


def get_watched_file_meta(*, view_id: str | None = None) -> WatchedFileMeta:
    st = get_view_state(view_id)
    if st.watched_file is None:
        raise LookupError("No watched file metadata available")
    return st.watched_file


def clear_watched_file_meta(*, view_id: str | None = None) -> None:
    st = get_view_state(view_id)
    st.watched_file = None
    _touch_render_revision(st)


# Backwards-compatible single-view API (uses active view)


def get_kind(view_id: str | None = None) -> str:
    return get_view_state(view_id).kind


def set_plot(
    png_bytes: bytes,
    *,
    view_id: str | None = None,
    publish_source: str | None = None,
) -> None:
    st = get_view_state(view_id)
    vid = view_id or _ACTIVE_VIEW_ID

    st.kind = "plot"
    st.icon_key = _icon_for_view_kind("plot")
    st.plot_png = png_bytes

    st.artifact = Artifact(
        kind="plot",
        obj=png_bytes,
        created_at=datetime.now(timezone.utc),
        view_id=vid,
    )

    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = None
    st.status["publish_source"] = _normalize_publish_source(publish_source)
    _clear_restored_status(st)
    _touch_render_revision(st)

    register_view(
        view_id=vid, kind="plot", icon_key=st.icon_key, activate_if_first=False
    )


def get_plot(*, view_id: str | None = None) -> bytes:
    st = get_view_state(view_id)
    if st.plot_png is None:
        raise LookupError("No plot available")
    return st.plot_png


def has_plot(*, view_id: str | None = None) -> bool:
    st = get_view_state(view_id)
    return st.plot_png is not None


def set_table(
    df: pd.DataFrame,
    html_simple: str | None,
    *,
    view_id: str | None = None,
    total_rows: int | None = None,
    returned_rows: int | None = None,
    publish_source: str | None = None,
) -> None:
    st = get_view_state(view_id)
    st.icon_key = _icon_for_view_kind("table")
    vid = view_id or _ACTIVE_VIEW_ID

    st.kind = "table"
    st.table_df = df
    st.table_html_simple = html_simple

    st.table_total_rows = total_rows
    st.table_returned_rows = returned_rows

    st.artifact = Artifact(
        kind="table",
        obj=df,
        created_at=datetime.now(timezone.utc),
        view_id=vid,
    )

    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = None
    st.status["publish_source"] = _normalize_publish_source(publish_source)
    _clear_restored_status(st)
    _touch_render_revision(st)

    register_view(
        view_id=vid, kind="table", icon_key=st.icon_key, activate_if_first=False
    )


def set_artifact(
    *,
    obj: Any,
    kind: ArtifactKind,
    label: str | None = None,
    section: str | None = None,
    view_id: str | None = None,
    truncation: Truncation | None = None,
    publish_source: str | None = None,
) -> None:
    st = get_view_state(view_id)
    vid = view_id or _ACTIVE_VIEW_ID

    st.kind = "artifact"
    st.icon_key = _icon_for_view_kind("artifact", artifact_kind=kind)
    st.artifact = Artifact(
        kind=kind,
        obj=obj,
        created_at=datetime.now(timezone.utc),
        label=label,
        section=section,
        view_id=vid,
        truncation=truncation,
    )

    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = None
    st.status["publish_source"] = _normalize_publish_source(publish_source)
    _clear_restored_status(st)
    _touch_render_revision(st)

    register_view(
        view_id=vid, kind="artifact", icon_key=st.icon_key, activate_if_first=False
    )


def has_table(*, view_id: str | None = None) -> bool:
    st = get_view_state(view_id)
    return st.table_df is not None


def has_artifact(*, view_id: str | None = None) -> bool:
    st = get_view_state(view_id)
    return st.artifact is not None


def get_artifact(*, view_id: str | None = None) -> Artifact:
    st = get_view_state(view_id)
    if st.artifact is None:
        raise LookupError("No artifact available")
    return st.artifact


def get_table_df(*, view_id: str | None = None) -> pd.DataFrame:
    st = get_view_state(view_id)
    if st.table_df is None:
        raise LookupError("No table available")
    return st.table_df


def get_table_html_simple(*, view_id: str | None = None) -> str:
    st = get_view_state(view_id)
    if st.table_html_simple is None:
        raise LookupError("No simple HTML table available")
    return st.table_html_simple


def get_table_counts(*, view_id: str | None = None) -> tuple[int | None, int | None]:
    st = get_view_state(view_id)
    return (st.table_total_rows, st.table_returned_rows)


# ------------------------------------------------------------------------------
# Status bookkeeping (per-view)
# ------------------------------------------------------------------------------


def mark_success(
    *,
    duration_s: float | None,
    view_id: str | None = None,
    publish_source: str | None = None,
) -> None:
    st = get_view_state(view_id)
    st.status["last_updated"] = _now_iso()
    st.status["last_duration_s"] = duration_s
    st.status["last_error"] = None
    st.status["publish_source"] = _normalize_publish_source(publish_source)
    _clear_restored_status(st)


def mark_error(message: str, *, view_id: str | None = None) -> None:
    st = get_view_state(view_id)
    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = message


def mark_restored(
    *,
    view_id: str,
    last_updated: str | None,
    restored_at: str | None = None,
    source: str = "latest",
) -> None:
    """
    Mark a view as restored from persisted storage.

    last_updated should represent the original publish/update timestamp, not the
    time the server restored it.
    """
    st = get_view_state(view_id)

    if last_updated:
        st.status["last_updated"] = last_updated

    st.status["last_error"] = None
    st.status["restored_from_storage"] = True
    st.status["restored_at"] = restored_at or _now_iso()
    st.status["restore_source"] = source


def get_status(*, view_id: str | None = None) -> dict[str, Any]:
    st = get_view_state(view_id)
    return dict(st.status)


def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_freshness(*, view_id: str | None = None) -> dict[str, Any]:
    """
    Compute freshness state for a view from its last_updated timestamp and config.

    States:
      - "disabled"
      - "unknown"
      - "ok"
      - "warn"
      - "error"

    Source-aware behaviour:
      - normal/Python publishes use global freshness
      - watched-file publishes do not use global freshness by default
      - watched-file publishes only use freshness when freshness-settings.views
        contains an explicit entry for that view
    """
    vid = view_id or _ACTIVE_VIEW_ID
    st = get_view_state(vid)

    publish_source = _normalize_publish_source(st.status.get("publish_source"))
    has_view_freshness = config.has_freshness_view_config(vid)

    enabled = config.get_freshness_enabled()
    if enabled:
        enabled = config.get_freshness_view_enabled(vid)

    expected_every_s = config.get_freshness_expected_every_s(vid)
    warn_after_s = config.get_freshness_warn_after_s(vid)
    overdue_after_s = config.get_freshness_overdue_after_s(vid)

    source_disabled = publish_source == "watch" and not has_view_freshness

    if not enabled or source_disabled:
        reason = None
        if source_disabled:
            reason = "watch_source_without_view_freshness"

        return {
            "enabled": False,
            "state": "disabled",
            "emoji": "",
            "label": "",
            "age_s": None,
            "expected_every_s": expected_every_s,
            "warn_after_s": warn_after_s,
            "overdue_after_s": overdue_after_s,
            "error_after_s": overdue_after_s,  # legacy alias
            "publish_source": publish_source,
            "source_disabled": source_disabled,
            "reason": reason,
        }

    if warn_after_s is None and expected_every_s is not None:
        warn_after_s = expected_every_s
    if overdue_after_s is None and warn_after_s is not None:
        overdue_after_s = warn_after_s * 2

    last_updated_raw = st.status.get("last_updated")
    last_updated_dt = _parse_iso_utc(last_updated_raw)

    if last_updated_dt is None:
        return {
            "enabled": True,
            "state": "unknown",
            "emoji": "⚪",
            "label": "No data yet",
            "age_s": None,
            "expected_every_s": expected_every_s,
            "warn_after_s": warn_after_s,
            "overdue_after_s": overdue_after_s,
            "error_after_s": overdue_after_s,  # legacy alias
            "publish_source": publish_source,
            "source_disabled": False,
            "reason": None,
        }

    now = datetime.now(timezone.utc)
    age_s = max(0, int((now - last_updated_dt).total_seconds()))

    state = "ok"
    emoji = "✅"
    label = "Fresh"

    if overdue_after_s is not None and age_s >= overdue_after_s:
        state = "error"
        emoji = "❌"
        label = "Overdue"
    elif warn_after_s is not None and age_s >= warn_after_s:
        state = "warn"
        emoji = "⚠️"
        label = "Stale"

    return {
        "enabled": True,
        "state": state,
        "emoji": emoji,
        "label": label,
        "age_s": age_s,
        "expected_every_s": expected_every_s,
        "warn_after_s": warn_after_s,
        "overdue_after_s": overdue_after_s,
        "error_after_s": overdue_after_s,  # legacy alias
        "publish_source": publish_source,
        "source_disabled": False,
        "reason": None,
    }


def _clear_restored_status(st: ViewState) -> None:
    st.status["restored_from_storage"] = False
    st.status["restored_at"] = None
    st.status["restore_source"] = None


# Publish throttling


def should_accept_publish(
    *, view_id: str, update_limit_s: int | None, now_s: float
) -> bool:
    """
    Server-side throttling:
      - if update_limit_s is None: accept
      - else accept only if enough time passed since last publish
    """
    if update_limit_s is None:
        return True

    st = get_view_state(view_id)
    if st.last_publish_at is None:
        st.last_publish_at = now_s
        return True

    if (now_s - st.last_publish_at) >= float(update_limit_s):
        st.last_publish_at = now_s
        return True

    return False


def note_publish(view_id: str, *, now_s: float) -> None:
    st = get_view_state(view_id)
    st.last_publish_at = now_s


# Service info + shutdown control (global)


def set_service_info(
    *, service_mode: bool, target: str | None, refresh_rate_s: int | None
) -> None:
    _SERVICE_INFO["service_mode"] = bool(service_mode)
    _SERVICE_INFO["service_target"] = target
    _SERVICE_INFO["service_refresh_rate_s"] = refresh_rate_s


def get_service_info() -> dict[str, Any]:
    return dict(_SERVICE_INFO)


def set_service_stop_hook(hook: Callable[[], None]) -> None:
    global _SERVICE_STOP_HOOK
    _SERVICE_STOP_HOOK = hook


def clear_service_stop_request() -> None:
    global _SERVICE_STOP_HOOK
    _SERVICE_STOP_HOOK = None


def request_service_stop() -> bool:
    global _SERVICE_STOP_HOOK

    if _SERVICE_STOP_HOOK is None:
        return False

    hook = _SERVICE_STOP_HOOK
    _SERVICE_STOP_HOOK = None
    try:
        hook()
    except Exception:
        pass
    return True


# Reset


def reset() -> None:
    """
    Reset all in-memory state.

    This is mainly used by unit tests to ensure isolation.
    """
    global _VIEWS, _VIEW_META, _ACTIVE_VIEW_ID
    global _SERVICE_INFO, _SERVICE_STOP_HOOK

    _VIEWS = {}
    _VIEW_META = {}
    _ACTIVE_VIEW_ID = "default"

    _SERVICE_INFO = {
        "service_mode": False,
        "service_target": None,
        "service_refresh_rate_s": None,
    }
    _SERVICE_STOP_HOOK = None


def _synchronise_store_api(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with _STORE_LOCK:
            return func(*args, **kwargs)

    return wrapped


for _store_api_name in (
    "register_view",
    "list_views",
    "set_active_view",
    "get_active_view_id",
    "get_view_menu_revision",
    "get_view_state",
    "get_render_revision",
    "set_watched_file_meta",
    "has_watched_file_meta",
    "get_watched_file_meta",
    "clear_watched_file_meta",
    "get_kind",
    "set_plot",
    "get_plot",
    "has_plot",
    "set_table",
    "set_artifact",
    "has_table",
    "has_artifact",
    "get_artifact",
    "get_table_df",
    "get_table_html_simple",
    "get_table_counts",
    "mark_success",
    "mark_error",
    "mark_restored",
    "get_status",
    "get_freshness",
    "should_accept_publish",
    "note_publish",
    "set_service_info",
    "get_service_info",
    "set_service_stop_hook",
    "clear_service_stop_request",
    "request_service_stop",
    "reset",
):
    globals()[_store_api_name] = _synchronise_store_api(globals()[_store_api_name])
