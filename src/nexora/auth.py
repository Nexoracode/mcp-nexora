import hmac
from urllib.parse import parse_qs

from starlette.responses import JSONResponse


class BearerAuth:
    """ASGI middleware: require the API key when one is configured.

    The key is accepted as `Authorization: Bearer <key>` or as a `?key=<key>` query parameter
    (for clients such as ChatGPT connectors that cannot send custom headers).
    """

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    def _allowed(self, scope) -> bool:
        headers = dict(scope["headers"])
        supplied = headers.get(b"authorization", b"").decode()
        if hmac.compare_digest(supplied, f"Bearer {self.api_key}"):
            return True
        query = parse_qs(scope.get("query_string", b"").decode())
        return hmac.compare_digest(query.get("key", [""])[0], self.api_key)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self.api_key and not self._allowed(scope):
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)
