"""Invocation-only browser UI editor; ordinary plotsrv never imports its server."""

from __future__ import annotations


def launch(args):
    import ipaddress
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
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not 0 <= args.port <= 65535:
            raise SaveError("Port must be between 0 and 65535.")
        if not loopback:
            print(
                "WARNING: remote config editor binding. Restrict access and use an HTTPS reverse proxy; the session key grants config-writing access. Prefer loopback with an SSH tunnel. Publisher bearer keys do not authorise this editor.",
                file=sys.stderr,
            )
            if not args.origin or not args.origin.startswith("https://"):
                raise SaveError(
                    "Non-loopback binding requires --origin https://HOST and a restricted TLS proxy."
                )
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
        authority = f"[{host}]" if ":" in host else host
        origin = browser_origin(args.origin or f"http://{authority}:{port}")
        token = secrets.token_urlsafe(32)
        app = create_app(
            draft,
            origin=origin,
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
                proxy_headers=False,
                limit_concurrency=8,
                timeout_keep_alive=3,
                timeout_graceful_shutdown=5,
            )
        )
        print(
            f"Open {origin}/\nTemporary session key (paste into the editor): {token}\nConfig: {draft.path}\nSession expires in one hour. Save, Cancel or Ctrl+C closes the editor.\nFor a headless host, forward port {port} over SSH; use --origin if the browser port differs.",
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
