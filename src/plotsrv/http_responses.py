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

    def __init__(self, content, *, release: Callable[[], None], **kwargs):
        super().__init__(content, **kwargs)
        self._owned_content = content
        self._release = release

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
