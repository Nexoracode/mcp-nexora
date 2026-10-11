"""Vercel entrypoint: normalises the request path and makes sure the MCP session manager is running."""
import asyncio

from nexora.server import app as _app
from nexora.server import mcp


class VercelApp:
    def __init__(self, inner):
        self.inner = inner
        self._lifespan_seen = False
        self._ready: asyncio.Event | None = None
        self._lock: asyncio.Lock | None = None

    async def _start_manager(self):
        started, stop = asyncio.Event(), asyncio.Event()

        async def runner():
            async with mcp.session_manager.run():
                started.set()
                await stop.wait()

        self._task = asyncio.create_task(runner())
        await started.wait()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            self._lifespan_seen = True
            return await self.inner(scope, receive, send)
        if scope["type"] == "http":
            if not self._lifespan_seen:
                self._lock = self._lock or asyncio.Lock()
                async with self._lock:
                    if self._ready is None:
                        self._ready = asyncio.Event()
                        await self._start_manager()
                        self._ready.set()
            scope = dict(scope, path="/mcp", raw_path=b"/mcp")
        return await self.inner(scope, receive, send)


app = VercelApp(_app)
