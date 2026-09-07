"""Append-only structured stream observation primitives.

The stream transport and browser representation deliberately live outside the
ordinary snapshot publisher.  This package starts with the source-facing API
so later stream protocol code can use the same follower for local and remote
plotsrv servers.
"""

from .api import StreamHandle, stream_view
from .file_source import JsonlBatch, JsonlFollower, JsonlRecord, resolve_jsonl_source
from .models import STREAM_PROTOCOL_VERSION

__all__ = [
    "JsonlFollower",
    "JsonlBatch",
    "JsonlRecord",
    "StreamHandle",
    "STREAM_PROTOCOL_VERSION",
    "resolve_jsonl_source",
    "stream_view",
]
