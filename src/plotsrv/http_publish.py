from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import config, store


def _container_item_count(obj: Any) -> int:
    if isinstance(obj, dict):
        n = len(obj)
        for v in obj.values():
            n += _container_item_count(v)
        return n
    if isinstance(obj, (list, tuple, set)):
        n = len(obj)
        for v in obj:
            n += _container_item_count(v)
        return n
    return 0


def _is_watch_publish_source(publish_source: str | None) -> bool:
    return (publish_source or "").strip().lower() == "watch"


def _publish_source_label(publish_source: str | None) -> str:
    return (publish_source or "normal").strip().lower()


def _http_detail_to_text(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    try:
        return str(detail)
    except Exception:  # noqa: BLE001 - defensive formatting of user objects
        return "Unknown publish error"


def _publish_rejection_artifact_text(
    *,
    status_code: int,
    detail: Any,
    view_id: str,
    kind: str,
    publish_source: str | None,
) -> str:
    detail_text = _http_detail_to_text(detail)

    return (
        "plotsrv publish rejected\n"
        "\n"
        f"Status: {status_code}\n"
        f"View: {view_id}\n"
        f"Kind: {kind}\n"
        f"Publish source: {_publish_source_label(publish_source)}\n"
        "\n"
        "What failed:\n"
        f"{detail_text}\n"
        "\n"
        "Adjust the config key mentioned above, or publish a smaller/truncated object.\n"
    )


def _record_publish_rejection_artifact(
    *,
    exc: HTTPException,
    view_id: str,
    section: Any,
    label: Any,
    kind: str,
    publish_source: str | None,
) -> None:
    """
    Make rejected normal Python publishes visible in the UI.

    Watch publishes have their own fallback path in runtime.py, so avoid
    duplicating that behaviour here.
    """
    if _is_watch_publish_source(publish_source):
        return

    msg = _publish_rejection_artifact_text(
        status_code=int(exc.status_code),
        detail=exc.detail,
        view_id=view_id,
        kind=kind,
        publish_source=publish_source,
    )

    try:
        store.set_artifact(
            obj=msg,
            kind="publish_error",
            label=label if isinstance(label, str) else None,
            section=section if isinstance(section, str) else None,
            view_id=view_id,
            publish_source=publish_source,
        )
        store.mark_error(msg, view_id=view_id)
    except Exception:  # noqa: BLE001 - preserve the original HTTP rejection
        # Never hide the original publish rejection.
        return


def _raise_publish_rejection(
    *,
    status_code: int,
    detail: str,
    view_id: str,
    section: Any,
    label: Any,
    kind: str,
    publish_source: str | None,
) -> None:
    exc = HTTPException(status_code=status_code, detail=detail)
    _record_publish_rejection_artifact(
        exc=exc,
        view_id=view_id,
        section=section,
        label=label,
        kind=kind,
        publish_source=publish_source,
    )
    raise exc


def _validate_artifact_size(
    obj: Any,
    *,
    publish_source: str | None = None,
) -> None:
    """
        Validate normal /publish artifact payloads.


    Watched files are source-aware: by the time they reach /publish, they should
    already have been controlled by limits.watched_files and limits.truncate_after.*.
    They should not also be rejected by limits.published_objects.*.
    """
    if _is_watch_publish_source(publish_source):
        return

    source = _publish_source_label(publish_source)
    max_text = config.get_publish_max_artifact_text_chars()
    max_items = config.get_publish_max_json_container_items()

    if isinstance(obj, str):
        actual = len(obj)
        if actual > max_text:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Artifact text payload has {actual} characters, exceeding "
                    f"limits.published_objects.max_artifact_text_chars={max_text}. "
                    f"publish_source={source}"
                ),
            )
        return

    if isinstance(obj, (dict, list, tuple, set)):
        actual = _container_item_count(obj)
        if actual > max_items:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Artifact JSON/container payload has {actual} items, exceeding "
                    f"limits.published_objects.max_json_container_items={max_items}. "
                    f"publish_source={source}"
                ),
            )
        return

    s = repr(obj)
    actual = len(s)
    if actual > max_text:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Artifact representation has {actual} characters, exceeding "
                f"limits.published_objects.max_artifact_text_chars={max_text}. "
                f"publish_source={source}"
            ),
        )
