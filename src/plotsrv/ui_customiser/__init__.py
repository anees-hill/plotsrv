"""Invocation-only browser UI editor; ordinary plotsrv never imports its server."""

from __future__ import annotations


def launch(args):
    from pathlib import Path
    import secrets
    import socket
    import sys
    import webbrowser

    from .. import settings
    from ..config_wizard.saving import SaveError
    from .model import Draft
    from .server import create_app, browser_origin
    import uvicorn

    server = None
    sock = None
    draft = None
    try:
        host = args.host
        if not 0 <= args.port <= 65535:
            raise SaveError("Port must be between 0 and 65535.")
        path = (
            Path(args.config)
            if args.config
            else settings.get_runtime_config_path() or Path.cwd() / "plotsrv.yml"
        )
        draft = Draft(
            path,
            name=args.name or settings.get_runtime_name(),
            assets_dir=args.assets_dir,
        )
        address = socket.getaddrinfo(host, args.port, type=socket.SOCK_STREAM)[0]
        sock = socket.socket(address[0], address[1], address[2])
        sock.bind(address[4])
        sock.listen(8)
        port = sock.getsockname()[1]
        browser_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
        authority = f"[{browser_host}]" if ":" in browser_host else browser_host
        origin = browser_origin(args.origin or f"http://{authority}:{port}")
        token = secrets.token_urlsafe(32)
        app = create_app(
            draft,
            origin=args.origin,
            token=token,
            on_close=lambda: setattr(server, "should_exit", True) if server else None,
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                access_log=False,
                log_level="critical",
                limit_concurrency=8,
                timeout_keep_alive=3,
                timeout_graceful_shutdown=5,
            )
        )
        print(
            f"Open {origin}/\nTemporary session key (paste into the editor): {token}\nConfig: {draft.path}\nSession expires in one hour. Save, Cancel or Ctrl+C closes the editor.\nListening on {host}:{port}. For remote access, use this machine's address with port {port}; SSH forwarding also works.",
            flush=True,
        )
        if not args.no_open:
            webbrowser.open(origin + "/")
        server.run(sockets=[sock])
        return 0
    except KeyboardInterrupt:
        return 0
    except SaveError as error:
        print(
            "Cannot start UI editor: " + str(error) + " Nothing was saved.",
            file=sys.stderr,
        )
        return 2
    except (ValueError, OSError):
        print(
            "Cannot start UI editor. Check config YAML, bind/origin options, port availability and approved asset directory. Nothing was saved.",
            file=sys.stderr,
        )
        return 2
    finally:
        if draft:
            draft.images.clear()
        if sock:
            sock.close()
