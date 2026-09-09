"""Shared deadline-aware HTTP mechanics; no endpoints, credentials or delivery policy.

Native system DNS resolution cannot be preempted by socket deadlines.
"""

import http.client
import io
import time
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("HTTP exchange deadline")
    return remaining


class _DeadlineReader(io.RawIOBase):
    """Check the total deadline on every socket read, including HTTP headers.

    A socket inactivity timeout alone resets on each byte from a trickling peer.
    No timer or worker is needed; closing this file releases its socket reference.
    """

    def __init__(self, sock, deadline, read_limit=None):
        self.sock, self.deadline = sock, deadline
        self.remaining_bytes = read_limit
        self.raw = sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        if self.remaining_bytes is not None:
            if self.remaining_bytes <= 0:
                raise ValueError("HTTP response read limit")
            count = self.raw.readinto(memoryview(buffer)[: self.remaining_bytes])
            self.remaining_bytes -= count or 0
            return count
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline, read_limit=None):
        self.sock, self.deadline = sock, deadline
        self.read_limit = read_limit

    def makefile(self, mode):
        return io.BufferedReader(
            _DeadlineReader(self.sock, self.deadline, self.read_limit)
        )


def _connection_type(base, deadline, read_limit=None):
    class Connection(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            create = self._create_connection

            def connect(address, timeout, source_address):
                sock = create(address, _remaining(deadline), source_address)
                try:
                    sock.settimeout(_remaining(deadline))
                    return sock
                except BaseException:
                    sock.close()
                    raise

            self._create_connection = connect
            self.response_class = lambda sock, *a, **kw: http.client.HTTPResponse(
                _DeadlineSocket(sock, deadline, read_limit), *a, **kw
            )

        def send(self, data):
            if self.sock is None:
                self.connect()
            self.sock.settimeout(_remaining(deadline))
            return super().send(data)

    return Connection


def open_http(request, *, timeout, use_environment_proxy=True, read_limit=None):
    deadline = time.monotonic() + timeout
    http_connection = _connection_type(http.client.HTTPConnection, deadline, read_limit)
    https_connection = _connection_type(
        http.client.HTTPSConnection, deadline, read_limit
    )

    class HTTP(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(http_connection, req)

    class HTTPS(urllib.request.HTTPSHandler):
        def https_open(self, req):
            # HTTPSConnection's default context verifies certificates/hostnames.
            return self.do_open(https_connection, req, context=self._context)

    handlers = [_NoRedirect(), HTTP(), HTTPS()]
    if not use_environment_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(
        request, timeout=_remaining(deadline)
    )
