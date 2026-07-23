"""Smithery Connect API client for user-specific Google Calendar MCP connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

SMITHERY_API_BASE_URL = "https://api.smithery.ai"


class SmitheryConfigError(RuntimeError):
    """Raised when Smithery server credentials are not configured."""


class SmitheryApiError(RuntimeError):
    """Raised when Smithery API returns an error response."""

    def __init__(
        self, message: str, *, status_code: int | None = None, payload: Any = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class SmitheryConnectionResult:
    connection_id: str
    name: str | None
    status: str
    authorization_url: str | None
    raw: dict[str, Any]

    @property
    def connected(self) -> bool:
        return self.status == "connected"


def _require_smithery_api_key() -> str:
    api_key = (settings.smithery_api_key or "").strip()
    if not api_key:
        raise SmitheryConfigError("SMITHERY_API_KEY is not configured.")
    return api_key


def get_smithery_namespace() -> str:
    return (settings.smithery_namespace or "law404").strip()


def get_google_calendar_mcp_url() -> str:
    return (
        settings.smithery_google_calendar_mcp_url
        or "https://server.smithery.ai/googlecalendar"
    ).strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_require_smithery_api_key()}",
        "Content-Type": "application/json",
    }


def _extract_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    status_payload = payload.get("status")
    if isinstance(status_payload, dict):
        state = str(status_payload.get("state") or "").strip()
        authorization_url = (
            status_payload.get("authorizationUrl")
            or status_payload.get("authorization_url")
            or status_payload.get("url")
        )
        return state or "unknown", str(authorization_url) if authorization_url else None

    if isinstance(status_payload, str):
        return status_payload, None

    return "unknown", None


def _parse_connection(payload: dict[str, Any]) -> SmitheryConnectionResult:
    status, authorization_url = _extract_status(payload)
    connection_id = str(
        payload.get("connectionId") or payload.get("connection_id") or ""
    )
    return SmitheryConnectionResult(
        connection_id=connection_id,
        name=payload.get("name"),
        status=status,
        authorization_url=authorization_url,
        raw=payload,
    )


async def create_or_update_google_calendar_connection(
    *,
    connection_id: str,
    user_id: int,
    user_label: str | None = None,
) -> SmitheryConnectionResult:
    """Create or update one Smithery Google Calendar connection for a Law-404 user."""
    namespace = get_smithery_namespace()
    url = f"{SMITHERY_API_BASE_URL}/connect/{namespace}/{connection_id}"
    payload = {
        "transport": "http",
        "mcpUrl": get_google_calendar_mcp_url(),
        "name": user_label or connection_id,
        "metadata": {
            "userId": str(user_id),
            "provider": "smithery_googlecalendar",
            "app": "law404",
        },
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.put(url, headers=_headers(), json=payload)

    if response.status_code >= 400:
        raise SmitheryApiError(
            "Smithery connection creation failed.",
            status_code=response.status_code,
            payload=_safe_json(response),
        )

    return _parse_connection(response.json())


async def get_smithery_connection(
    *,
    connection_id: str,
) -> SmitheryConnectionResult:
    """Fetch one Smithery connection and return its current status."""
    namespace = get_smithery_namespace()
    url = f"{SMITHERY_API_BASE_URL}/connect/{namespace}/{connection_id}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=_headers())

    if response.status_code >= 400:
        raise SmitheryApiError(
            "Smithery connection lookup failed.",
            status_code=response.status_code,
            payload=_safe_json(response),
        )

    return _parse_connection(response.json())


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
