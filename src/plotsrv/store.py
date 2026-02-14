# src/plotsrv/store.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
from .artifacts import Artifact


# ------------------------------------------------------------------------------
# Models
# ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ViewMeta:
    """
    Metadata that describes a view shown in the UI dropdown.
    """

    view_id: str
    kind: str  # "none" | "plot" | "table"
    label: str
    section: str | None = None


@dataclass(slots=True)
class ViewState:
    """
    Per-view state that the UI can display.

    Each view is independent: plot/table/status.
    """

    kind: str = "none"  # "none" | "plot" | "table"
    plot_png: bytes | None = None
    table_df: pd.DataFrame | None = None
    table_html_simple: str | None = None
    status: dict[str, Any] = None  # populated in __post_init__
    table_total_rows: int | None = None
    table_returned_rows: int | None = None
    artifact: Artifact | None = None

    # publish throttling
    last_publish_at: float | None = None  # epoch seconds

    def __post_init__(self) -> None:
        if self.status is None:
            self.status = {
                "last_updated": None,  # ISO string
                "last_duration_s": None,  # float | None
                "last_error": None,  # str | None
            }


# ------------------------------------------------------------------------------
# Global store: multi-view
# ------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_view(view_id: str) -> ViewState:
    if view_id not in _VIEWS:
        _VIEWS[view_id] = ViewState()
    return _VIEWS[view_id]


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


# ------------------------------------------------------------------------------
# View registry API
# ------------------------------------------------------------------------------


def register_view(
    *,
    view_id: str | None = None,
    section: str | None = None,
    label: str | None = None,
    kind: str = "none",
    activate_if_first: bool = True,
) -> str:
    vid = normalize_view_id(view_id, section=section, label=label)
    st = _ensure_view(vid)

    # allow "upgrading" a view kind once it receives content
    if kind in ("plot", "table"):
        st.kind = kind

    meta = _VIEW_META.get(vid)
    if meta is None:
        _VIEW_META[vid] = ViewMeta(
            view_id=vid,
            kind=st.kind,
            label=(label or vid),
            section=section,
        )
    else:
        # keep label/section if new values supplied
        _VIEW_META[vid] = ViewMeta(
            view_id=vid,
            kind=st.kind,
            label=(label or meta.label),
            section=(section if section is not None else meta.section),
        )

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
    Return UI-ready view metadata, stable ordering:
      section then label.
    """
    metas = list(_VIEW_META.values())

    def _key(m: ViewMeta) -> tuple[str, str]:
        sec = m.section or ""
        return (sec, m.label)

    return sorted(metas, key=_key)


def set_active_view(view_id: str) -> None:
    global _ACTIVE_VIEW_ID
    _ACTIVE_VIEW_ID = view_id
    _ensure_view(view_id)


def get_active_view_id() -> str:
    return _ACTIVE_VIEW_ID


def get_view_state(view_id: str | None = None) -> ViewState:
    vid = view_id or _ACTIVE_VIEW_ID
    return _ensure_view(vid)


# ------------------------------------------------------------------------------
# Backwards-compatible single-view API (uses active view)
# ------------------------------------------------------------------------------


def get_kind(view_id: str | None = None) -> str:
    return get_view_state(view_id).kind


def set_plot(png_bytes: bytes, *, view_id: str | None = None) -> None:
    st = get_view_state(view_id)
    vid = view_id or _ACTIVE_VIEW_ID

    st.kind = "plot"
    st.plot_png = png_bytes

    st.artifact = Artifact(
        kind="plot",
        obj=png_bytes,
        created_at=datetime.now(timezone.utc),
        view_id=vid,
    )

    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = None


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
) -> None:
    st = get_view_state(view_id)
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


def set_artifact(
    *,
    obj: Any,
    kind: str,
    label: str | None = None,
    section: str | None = None,
    view_id: str | None = None,
) -> None:
    """
    Store an arbitrary artifact for the view.

    Note: we do NOT force `st.kind = "artifact"` here because existing UX still
    treats "plot" and "table" as first-class. The artifact itself carries the
    true kind ("text"/"json"/"python"/"plot"/"table"/etc).
    """
    st = get_view_state(view_id)
    vid = view_id or _ACTIVE_VIEW_ID

    st.artifact = Artifact(
        kind=kind,  # e.g. "text"|"json"|"python" (or "plot"/"table" too)
        obj=obj,
        created_at=datetime.now(timezone.utc),
        label=label,
        section=section,
        view_id=vid,
    )

    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = None


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


def mark_success(*, duration_s: float | None, view_id: str | None = None) -> None:
    st = get_view_state(view_id)
    st.status["last_updated"] = _now_iso()
    st.status["last_duration_s"] = duration_s
    st.status["last_error"] = None


def mark_error(message: str, *, view_id: str | None = None) -> None:
    st = get_view_state(view_id)
    st.status["last_updated"] = _now_iso()
    st.status["last_error"] = message


def get_status(*, view_id: str | None = None) -> dict[str, Any]:
    st = get_view_state(view_id)
    return dict(st.status)


# ------------------------------------------------------------------------------
# Publish throttling
# ------------------------------------------------------------------------------


def should_accept_publish(
    *,
    view_id: str,
    update_limit_s: int | None,
    now_s: float,
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


# ------------------------------------------------------------------------------
# Service info + shutdown control (global)
# ------------------------------------------------------------------------------


def set_service_info(
    *,
    service_mode: bool,
    target: str | None,
    refresh_rate_s: int | None,
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


# ------------------------------------------------------------------------------
# Reset
# ------------------------------------------------------------------------------


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
