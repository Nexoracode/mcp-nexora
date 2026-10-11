"""MCP tools backed by the Nexora owner API (/api/owner/*) instead of raw SQL.

Writes go through the panel's own business rules. Every mutating tool needs `confirm=true`;
without it the tool returns what it would do (with the current state) and changes nothing.
"""
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import Settings

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

ASK = (
    "Mutating tool. Call it first WITHOUT confirm to get a preview, show that to the user, and call again "
    "with confirm=true ONLY after the user explicitly agrees in chat."
)


class NexoraAPI:
    def __init__(self, s: Settings):
        self._base = s.nexora_api_url.rstrip("/") + "/api/owner"
        self._headers = {"Authorization": f"Bearer {s.nexora_api_token}"}

    async def call(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.request(method, self._base + path, headers=self._headers, params=params, json=json)
        try:
            data = r.json()
        except ValueError:
            data = {"message": r.text[:200]}
        if r.status_code >= 400:
            raise ValueError(f"Nexora API {r.status_code}: {data.get('message', data)}")
        return data


def register(mcp: FastMCP, s: Settings) -> None:
    api = NexoraAPI(s)

    def preview(action: str, details: dict, current: Any = None) -> dict:
        return {
            "requires_confirmation": True,
            "action": action,
            "details": details,
            "current_state": current,
            "next_step": "Show this to the user. If they agree, call the same tool again with the same arguments and confirm=true.",
        }

    async def _find(path: str, key: str, value: str, params: dict | None = None) -> Any:
        data = await api.call("GET", path, params={"limit": 100, **(params or {})})
        return next((x for x in data.get(key, []) if x.get("id") == value), None)

    # ---------------------------------------------------------------- reads
    @mcp.tool(annotations=READ)
    async def nexora_summary() -> dict:
        """Counts: sites, active sites, pending purchases, pending wallet top-ups, open and answered tickets."""
        return await api.call("GET", "/summary")

    @mcp.tool(annotations=READ)
    async def list_sites(q: str | None = None, status: Literal["ACTIVE", "SUSPENDED"] | None = None, limit: int = 20, offset: int = 0) -> dict:
        """Customer sites (domain, client, status, contract price, wallet balance). `q` searches domain and client name."""
        return await api.call("GET", "/sites", params={"q": q, "status": status, "limit": limit, "offset": offset})

    @mcp.tool(annotations=READ)
    async def get_site(site_id: str) -> dict:
        """One site with its features, recent license events and counts. Never includes the license key."""
        return await api.call("GET", f"/sites/{site_id}")

    @mcp.tool(annotations=READ)
    async def site_wallet(site_id: str, limit: int = 20, offset: int = 0) -> dict:
        """A site's wallet balance and transaction history, newest first."""
        return await api.call("GET", f"/sites/{site_id}/wallet", params={"limit": limit, "offset": offset})

    @mcp.tool(annotations=READ)
    async def list_features() -> dict:
        """The feature catalog: key, title, group, price, isActive and how many sites own each."""
        return await api.call("GET", "/features")

    @mcp.tool(annotations=READ)
    async def list_packages() -> dict:
        """Feature packages with their price and feature keys."""
        return await api.call("GET", "/packages")

    @mcp.tool(annotations=READ)
    async def list_purchases(status: Literal["PENDING", "APPROVED", "REJECTED", "AWAITING_PAYMENT", "FAILED"] | None = "PENDING", limit: int = 20, offset: int = 0) -> dict:
        """Purchase requests from customer sites (default: pending ones waiting for approval)."""
        return await api.call("GET", "/purchases", params={"status": status, "limit": limit, "offset": offset})

    @mcp.tool(annotations=READ)
    async def list_topups(status: Literal["AWAITING_PAYMENT", "PENDING", "APPROVED", "REJECTED", "FAILED"] | None = "PENDING", limit: int = 20, offset: int = 0) -> dict:
        """Wallet top-up requests (default: pending card-to-card ones waiting for approval)."""
        return await api.call("GET", "/topups", params={"status": status, "limit": limit, "offset": offset})

    @mcp.tool(annotations=READ)
    async def list_tickets(status: Literal["OPEN", "ANSWERED", "CLOSED", "AWAITING_PAYMENT"] | None = None, q: str | None = None, limit: int = 20, offset: int = 0) -> dict:
        """Support tickets, most recently updated first. `q` searches the subject."""
        return await api.call("GET", "/tickets", params={"status": status, "q": q, "limit": limit, "offset": offset})

    @mcp.tool(annotations=READ)
    async def get_ticket(ticket_id: str) -> dict:
        """A support ticket with its whole conversation."""
        return await api.call("GET", f"/tickets/{ticket_id}")

    @mcp.tool(annotations=READ)
    async def list_ratings(limit: int = 20, offset: int = 0) -> dict:
        """Star ratings customers gave to features and packages."""
        return await api.call("GET", "/ratings", params={"limit": limit, "offset": offset})

    # --------------------------------------------------------------- writes
    @mcp.tool(annotations=WRITE, description=f"Change a site: status (ACTIVE/SUSPENDED), contract price, free-support months, notes, features to add/remove. Suspending a site cuts its optional features. {ASK}")
    async def update_site(
        site_id: str,
        status: Literal["ACTIVE", "SUSPENDED"] | None = None,
        contract_price: int | None = None,
        support_free_months: int | None = None,
        notes: str | None = None,
        add_features: list[str] | None = None,
        remove_features: list[str] | None = None,
        confirm: bool = False,
    ) -> dict:
        body = {k: v for k, v in {"status": status, "contractPrice": contract_price, "supportFreeMonths": support_free_months, "notes": notes, "addFeatures": add_features, "removeFeatures": remove_features}.items() if v is not None}
        if not body:
            raise ValueError("Nothing to change.")
        if not confirm:
            return preview(f"Update site {site_id}", body, await api.call("GET", f"/sites/{site_id}"))
        return await api.call("PATCH", f"/sites/{site_id}", json=body)

    @mcp.tool(annotations=WRITE, description=f"Credit or debit a site's wallet by a whole amount in toman with a reason. {ASK}")
    async def adjust_wallet(site_id: str, direction: Literal["credit", "debit"], amount: int, description: str, confirm: bool = False) -> dict:
        body = {"direction": direction, "amount": amount, "description": description}
        if not confirm:
            return preview(f"{direction} {amount:,} toman on site {site_id}", body, await api.call("GET", f"/sites/{site_id}/wallet", params={"limit": 3}))
        return await api.call("POST", f"/sites/{site_id}/wallet", json=body)

    @mcp.tool(annotations=WRITE, description=f"Edit a catalog feature: title, group, description, price (toman), isActive. Sites that already own it keep it. {ASK}")
    async def update_feature(
        key: str,
        title: str | None = None,
        group: str | None = None,
        description: str | None = None,
        price: int | None = None,
        is_active: bool | None = None,
        confirm: bool = False,
    ) -> dict:
        body = {k: v for k, v in {"title": title, "group": group, "description": description, "price": price, "isActive": is_active}.items() if v is not None}
        if not body:
            raise ValueError("Nothing to change.")
        if not confirm:
            features = (await api.call("GET", "/features"))["features"]
            return preview(f"Update feature {key}", body, next((f for f in features if f["key"] == key), None))
        return await api.call("PATCH", f"/features/{key}", json=body)

    @mcp.tool(annotations=WRITE, description=f"Create a package: name, price (toman) and the feature keys it contains. {ASK}")
    async def create_package(name: str, price: int, feature_keys: list[str], confirm: bool = False) -> dict:
        body = {"name": name, "price": price, "featureKeys": feature_keys}
        if not confirm:
            return preview("Create package", body)
        return await api.call("POST", "/packages", json=body)

    @mcp.tool(annotations=WRITE, description=f"Edit a package's name, price or full feature list (feature_keys replaces the list). {ASK}")
    async def update_package(package_id: str, name: str | None = None, price: int | None = None, feature_keys: list[str] | None = None, confirm: bool = False) -> dict:
        body = {k: v for k, v in {"name": name, "price": price, "featureKeys": feature_keys}.items() if v is not None}
        if not body:
            raise ValueError("Nothing to change.")
        if not confirm:
            packages = (await api.call("GET", "/packages"))["packages"]
            return preview(f"Update package {package_id}", body, next((p for p in packages if p["id"] == package_id), None))
        return await api.call("PATCH", f"/packages/{package_id}", json=body)

    @mcp.tool(annotations=WRITE, description=f"Approve a pending purchase request: the feature/package is added to the site. {ASK}")
    async def approve_purchase(purchase_id: str, confirm: bool = False) -> dict:
        if not confirm:
            return preview(f"Approve purchase {purchase_id}", {}, await _find("/purchases", "purchases", purchase_id, {"status": "PENDING"}))
        return await api.call("POST", f"/purchases/{purchase_id}/approve")

    @mcp.tool(annotations=WRITE, description=f"Reject a pending purchase request with a reason the buyer will read (3-500 chars). {ASK}")
    async def reject_purchase(purchase_id: str, reason: str, confirm: bool = False) -> dict:
        if not confirm:
            return preview(f"Reject purchase {purchase_id}", {"reason": reason}, await _find("/purchases", "purchases", purchase_id, {"status": "PENDING"}))
        return await api.call("POST", f"/purchases/{purchase_id}/reject", json={"reason": reason})

    @mcp.tool(annotations=WRITE, description=f"Approve a pending wallet top-up: the amount is credited to the site's wallet. {ASK}")
    async def approve_topup(topup_id: str, confirm: bool = False) -> dict:
        if not confirm:
            return preview(f"Approve top-up {topup_id}", {}, await _find("/topups", "topups", topup_id, {"status": "PENDING"}))
        return await api.call("POST", f"/topups/{topup_id}/approve")

    @mcp.tool(annotations=WRITE, description=f"Reject a pending wallet top-up with a reason (3-500 chars). {ASK}")
    async def reject_topup(topup_id: str, reason: str, confirm: bool = False) -> dict:
        if not confirm:
            return preview(f"Reject top-up {topup_id}", {"reason": reason}, await _find("/topups", "topups", topup_id, {"status": "PENDING"}))
        return await api.call("POST", f"/topups/{topup_id}/reject", json={"reason": reason})

    @mcp.tool(annotations=WRITE, description=f"Reply to a support ticket as the owner; the customer's site will show this message. {ASK}")
    async def reply_ticket(ticket_id: str, body: str, confirm: bool = False) -> dict:
        if not confirm:
            return preview(f"Reply to ticket {ticket_id}", {"body": body}, await api.call("GET", f"/tickets/{ticket_id}"))
        return await api.call("POST", f"/tickets/{ticket_id}/reply", json={"body": body})

    @mcp.tool(annotations=WRITE, description=f"Close an open or answered support ticket. {ASK}")
    async def close_ticket(ticket_id: str, confirm: bool = False) -> dict:
        if not confirm:
            return preview(f"Close ticket {ticket_id}", {}, await api.call("GET", f"/tickets/{ticket_id}"))
        return await api.call("POST", f"/tickets/{ticket_id}/close")
