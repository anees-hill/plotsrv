"""Foreground serving without application discovery, import or source workers."""

from __future__ import annotations


def serve(
    *, host: str | None = None, port: int | None = None, quiet: bool = False
) -> int:
    import uvicorn
    from . import config, store
    from .app import app
    from .connection_config import get_server_connection_config
    from .ingestion import setup_ingestion
    from .server import (
        restore_latest_views_from_storage,
        restore_streams_from_storage,
        stop_server,
    )
    from .storage.stream_worker import open_stream_storage_admission

    cfg = get_server_connection_config()
    bind_host = cfg.bind_host if host is None else host
    bind_port = cfg.bind_port if port is None else port
    from .publishing.models import PublishTarget

    PublishTarget("local", host=bind_host, port=bind_port)
    setup_ingestion(bind_host)
    open_stream_storage_admission()
    scope = config.get_storage_latest_restore_scope()
    # A standalone server has no discovered catalogue. Stored logical metadata
    # provides display identity; admission still gates every restored write.
    restore_latest_views_from_storage(
        restore_scope="all" if scope == "discovered" else scope
    )
    restore_streams_from_storage()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=bind_host,
            port=bind_port,
            log_level="warning" if quiet else "info",
        )
    )
    store.set_service_stop_hook(lambda: setattr(server, "should_exit", True))
    print("plotsrv: Waiting for a publisher", flush=True)
    try:
        server.run()
    finally:
        store.clear_service_stop_request()
        stop_server(join=True)
    return 0
