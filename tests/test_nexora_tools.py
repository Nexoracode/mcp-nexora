import asyncio
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

TOKEN = "t" * 40
calls: list[tuple[str, str, dict | None, str]] = []


class Stub(BaseHTTPRequestHandler):
    def _reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        n = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        calls.append((self.command, self.path, body, self.headers.get("authorization", "")))
        if self.path.startswith("/api/owner/sites/missing"):
            return self._reply(404, {"message": "سایت پیدا نشد."})
        if self.path.startswith("/api/owner/purchases"):
            return self._reply(200, {"total": 1, "purchases": [{"id": "p1", "status": "PENDING", "site": {"domain": "a.ir"}}]})
        self._reply(200, {"id": "s1", "status": "ACTIVE", "ok": True})

    do_GET = do_POST = do_PATCH = _handle

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server_module():
    httpd = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    import os

    env = {"DB_USER": "x", "DB_NAME": "y", "NEXORA_API_URL": f"http://127.0.0.1:{httpd.server_port}", "NEXORA_API_TOKEN": TOKEN}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    import nexora.server as server

    yield importlib.reload(server)
    httpd.shutdown()
    for k, v in old.items():
        os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def call(server, name, args):
    return asyncio.run(server.mcp.call_tool(name, args))


def test_tools_registered_and_sql_writes_off_by_default(server_module):
    names = {t.name for t in asyncio.run(server_module.mcp.list_tools())}
    assert {"list_sites", "approve_purchase", "adjust_wallet", "reply_ticket", "run_select"} <= names
    assert not {"preview_write", "execute_write"} & names


def test_mutation_without_confirm_changes_nothing(server_module):
    calls.clear()
    result = call(server_module, "update_site", {"site_id": "s1", "status": "SUSPENDED"})
    assert "requires_confirmation" in json.dumps(result, default=str)
    assert all(method == "GET" for method, *_ in calls)


def test_confirmed_mutation_sends_patch_with_bearer(server_module):
    calls.clear()
    call(server_module, "update_site", {"site_id": "s1", "status": "SUSPENDED", "confirm": True})
    method, path, body, auth = calls[-1]
    assert (method, path, body, auth) == ("PATCH", "/api/owner/sites/s1", {"status": "SUSPENDED"}, f"Bearer {TOKEN}")


def test_approve_preview_shows_the_request_then_posts(server_module):
    calls.clear()
    preview = json.dumps(call(server_module, "approve_purchase", {"purchase_id": "p1"}), default=str)
    assert "a.ir" in preview and all(m == "GET" for m, *_ in calls)
    call(server_module, "approve_purchase", {"purchase_id": "p1", "confirm": True})
    assert calls[-1][:2] == ("POST", "/api/owner/purchases/p1/approve")


def test_api_errors_surface_their_message(server_module):
    with pytest.raises(Exception, match="سایت پیدا نشد"):
        call(server_module, "get_site", {"site_id": "missing"})
