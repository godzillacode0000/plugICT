"""
AgentMail delivery adapter for PlugICT buyer fulfilment.

The API key is read only from AGENTMAIL_API_KEY. The inbox identifier is read
from AGENTMAIL_INBOX. Neither belongs in source control or chat.

Official API shape used here:
  POST https://api.agentmail.to/v0/inboxes/{inbox_id}/messages/send
  Authorization: Bearer <API key>

AgentMail accepts attachments as base64-encoded content and returns a
message_id and thread_id. Payment verification remains outside this module.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_API_BASE_URL = "https://api.agentmail.to/v0"


class AgentMailError(RuntimeError):
    """A safe, non-secret AgentMail API/configuration error."""


def _required(value: str | None, name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise AgentMailError(f"{name} is required for AgentMail delivery")
    return value


def _address_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    return [str(item).strip() for item in value if str(item).strip()]


def build_license_payload(
    *,
    buyer_email: str,
    subject: str,
    text: str,
    html: str,
    license_path: str | Path,
    bcc: str | list[str] | tuple[str, ...] | None = None,
    reply_to: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Build the JSON body for an AgentMail license delivery message."""
    buyer_email = _required(buyer_email, "buyer_email").lower()
    path = Path(license_path)
    if not path.is_file():
        raise AgentMailError(f"license attachment does not exist: {path.name}")

    bcc_values = [addr for addr in _address_list(bcc) if addr.lower() != buyer_email]
    reply_values = _address_list(reply_to)
    attachment = {
        "filename": "license.key",
        "content_type": "application/octet-stream",
        "content_disposition": "attachment",
        "content": base64.b64encode(path.read_bytes()).decode("ascii"),
    }

    payload: dict[str, Any] = {
        "to": [buyer_email],
        "subject": subject,
        "text": text,
        "html": html,
        "attachments": [attachment],
    }
    if bcc_values:
        payload["bcc"] = bcc_values
    if reply_values:
        payload["reply_to"] = reply_values
    return payload


def send_message(
    *,
    inbox_id: str | None,
    payload: dict[str, Any],
    api_key: str | None = None,
    api_base_url: str | None = None,
    timeout: float | None = None,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, str]:
    """Send a prepared AgentMail message and return safe delivery metadata."""
    api_key = _required(api_key or os.environ.get("AGENTMAIL_API_KEY"), "AGENTMAIL_API_KEY")
    inbox_id = _required(inbox_id or os.environ.get("AGENTMAIL_INBOX"), "AGENTMAIL_INBOX")
    base_url = (api_base_url or os.environ.get("AGENTMAIL_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")
    timeout_value = float(timeout or os.environ.get("AGENTMAIL_TIMEOUT_SECONDS", "30"))
    url = f"{base_url}/inboxes/{quote(inbox_id, safe='')}/messages/send"

    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with opener(request, timeout=timeout_value) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        # Never include request headers or the API key in an error.
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = "no response body"
        raise AgentMailError(f"AgentMail HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise AgentMailError(f"AgentMail network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise AgentMailError("AgentMail request timed out") from exc

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgentMailError("AgentMail returned invalid JSON") from exc

    message_id = str(result.get("message_id") or "").strip()
    thread_id = str(result.get("thread_id") or "").strip()
    if not message_id or not thread_id:
        raise AgentMailError("AgentMail response did not include message_id and thread_id")

    return {
        "provider": "agentmail",
        "status": "sent",
        "message_id": message_id,
        "thread_id": thread_id,
    }


def send_license(
    *,
    buyer_email: str,
    license_id: str,
    license_path: str | Path,
    subject: str,
    text: str,
    html: str,
    bcc: str | list[str] | tuple[str, ...] | None = None,
    reply_to: str | list[str] | tuple[str, ...] | None = None,
    **kwargs: Any,
) -> dict[str, str]:
    """Build and send a PlugICT license email through AgentMail."""
    del license_id  # Kept in the signature for a stable fulfilment adapter API.
    payload = build_license_payload(
        buyer_email=buyer_email,
        subject=subject,
        text=text,
        html=html,
        license_path=license_path,
        bcc=bcc,
        reply_to=reply_to,
    )
    return send_message(payload=payload, **kwargs)
