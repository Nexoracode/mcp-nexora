import hmac

from starlette.responses import JSONResponse


class BearerAuth:
    """ASGI middleware: require `Authorization: Bearer <key>` when a key is configured."""

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.api_key:
            headers = dict(scope["headers"])
            supplied = headers.get(b"authorization", b"").decode()
            if not hmac.compare_digest(supplied, f"Bearer {self.api_key}"):
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)
