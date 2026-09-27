"""Response lifetimes own resources, including before body iteration starts."""

from collections.abc import Callable

import anyio
from starlette.responses import StreamingResponse


class OwnedStreamingResponse(StreamingResponse):
    """Always close a stream and release its externally acquired resources.

    A generator's finally block is not entered when a client disconnects
    before its first iteration. Background tasks also do not cover every
    ASGI send failure, so cleanup belongs around the whole response call.
    The release callback must be idempotent for direct iterator consumers.
    """

    def __init__(self, content, *, release: Callable[[], None], max_duration_s: float | None = None, **kwargs):
        super().__init__(content, **kwargs)
        self._owned_content = content
        self._release = release
        self._max_duration_s = max_duration_s

    async def stream_response(self, send):
        if self._max_duration_s is None:
            return await super().stream_response(send)
        # Include blocked writes, not only time spent awaiting the next event.
        with anyio.move_on_after(self._max_duration_s) as deadline:
            await super().stream_response(send)
        if deadline.cancel_called:
            # Healthy clients see a clean EOF and reconnect. A blocked client
            # gets only a short grace period before the response releases slots.
            with anyio.move_on_after(1):
                await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                with anyio.CancelScope(shield=True):
                    if hasattr(self._owned_content, "aclose"):
                        await self._owned_content.aclose()
                    elif hasattr(self._owned_content, "close"):
                        self._owned_content.close()
            finally:
                self._release()
