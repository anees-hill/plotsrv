"""Shared local/HTTP observation receipt. No publisher filesystem or source access."""

from __future__ import annotations

import time

from .summary import validate_summary


def receive_observation(payload: dict) -> dict:
    from .. import store
    from ..contracts import SourceMetadata, ViewDescriptor
    from ..ingestion import IngestionError, register_catalogue, require_admitted, state
    from ..storage.worker import enqueue_snapshot

    view_id = payload.get("view_id")
    require_admitted(view_id)
    if payload.get("kind") != "artifact" or payload.get("artifact_kind") != "json":
        raise IngestionError("invalid_request", 422, "invalid_observation_metadata")
    try:
        if type(payload.get("force", False)) is not bool:
            raise ValueError("invalid force")
        interval = payload.get("update_limit_s")
        if interval is not None and (
            type(interval) is not int or not 0 <= interval <= 86400
        ):
            raise ValueError("invalid interval")
        summary = validate_summary(payload.get("observation"), view_id=view_id)
        label, section = payload.get("label") or view_id, payload.get("section")
        descriptor = ViewDescriptor(
            view_id,
            label,
            section,
            kind="artifact",
            capabilities=("json", "observation-v1"),
            source=SourceMetadata(source_type=summary["source_type"]),
        )
    except (TypeError, ValueError, KeyError):
        raise IngestionError("invalid_request", 422, "invalid_observation") from None
    now = time.time()
    with store._STORE_LOCK:
        require_admitted(view_id)
        previous = state().descriptors.get(view_id)
        if previous is not None:
            from dataclasses import replace

            descriptor = replace(descriptor, description=previous.description)
        if not payload.get("force") and not store.should_accept_publish(
            view_id=view_id, update_limit_s=payload.get("update_limit_s"), now_s=now
        ):
            return {
                "ok": True,
                "ignored": True,
                "reason": "throttled",
                "view_id": view_id,
            }
        register_catalogue([descriptor], seal=False)
        store.set_artifact(
            obj=summary,
            kind="json",
            view_id=view_id,
            label=label,
            section=section,
            publish_source="observation",
        )
        # Ordinary content replacement clears previous source capabilities.
        # Restore this already-validated descriptor in the same store transaction.
        state().descriptors[view_id] = descriptor
        store.mark_success(
            duration_s=None, view_id=view_id, publish_source="observation"
        )
        store.note_publish(view_id, now_s=now)
    # Persistence is the existing optional bounded snapshot path, with only
    # compact exported summaries. No second history store is introduced here.
    enqueue_snapshot(
        view_id=view_id,
        kind="json",
        obj=summary,
        label=label,
        section=section,
        source="observation",
    )
    return {"ok": True, "ignored": False, "view_id": view_id}
