from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from .models import ApprovalMessage, DeliveryResult, DiscordMessageRef, NotificationMessage


class DiscordClient:
    """Small synchronous adapter with injectable httpx transport for tests."""

    def __init__(
        self,
        webhooks: Mapping[str, str],
        bot_token: str,
        *,
        api_base: str = "https://discord.com/api/v10",
        http: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._webhooks = dict(webhooks)
        self._bot_token = bot_token
        self._api_base = api_base.rstrip("/")
        self._http = http or httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0))
        self._owns_http = http is None
        self._sleeper = sleeper

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def send(self, notification: NotificationMessage) -> DeliveryResult:
        url = self._webhooks.get(notification.destination, "")
        if not url.strip():
            return DeliveryResult.failed(0, "NOT_CONFIGURED")
        suffix = "&wait=true" if "?" in url else "?wait=true"
        payload: dict = {
            "content": notification.content,
            "allowed_mentions": {"parse": []},
        }
        # Chỉ thêm embed nếu có title, description hoặc fields
        if notification.title or notification.content or notification.fields:
            embed: dict[str, object] = {}
            if notification.title:
                embed["title"] = notification.title
            if notification.content:
                embed["description"] = notification.content
            if notification.fields:
                embed["fields"] = [
                    {"name": name, "value": value, "inline": True}
                    for name, value in notification.fields.items()
                ]
            payload["embeds"] = [embed]
        return self._request(
            "POST",
            f"{url}{suffix}",
            payload,
        )

    def send_approval(self, message: ApprovalMessage) -> DeliveryResult:
        return self._request(
            "POST",
            f"{self._api_base}/channels/{message.channel_id}/messages",
            self._approval_body(message, disabled=False),
            authenticated=True,
        )

    def finish_approval(self, reference: DiscordMessageRef, message: ApprovalMessage) -> DeliveryResult:
        return self._request(
            "PATCH",
            f"{self._api_base}/channels/{reference.channel_id}/messages/{reference.message_id}",
            self._approval_body(message, disabled=True),
            authenticated=True,
        )

    def finish_interaction(self, application_id: str, token: str, content: str) -> DeliveryResult:
        return self._request(
            "PATCH",
            f"{self._api_base}/webhooks/{application_id}/{token}/messages/@original",
            {"content": content, "allowed_mentions": {"parse": []}},
        )

    @staticmethod
    def _approval_body(message: ApprovalMessage, *, disabled: bool) -> dict[str, Any]:
        return {
            "content": message.content,
            "allowed_mentions": {"parse": []},
            "components": [
                {
                    "type": 1,
                    "components": [
                        {"type": 2, "style": 3, "label": "Approve", "custom_id": message.approve_id, "disabled": disabled},
                        {"type": 2, "style": 4, "label": "Reject", "custom_id": message.reject_id, "disabled": disabled},
                    ],
                }
            ],
        }

    def _request(self, method: str, url: str, payload: dict[str, Any], *, authenticated: bool = False) -> DeliveryResult:
        if authenticated and not self._bot_token.strip():
            return DeliveryResult.failed(0, "NOT_CONFIGURED")
        headers = {"Authorization": f"Bot {self._bot_token}"} if authenticated else {}
        for attempt in range(3):
            try:
                response = self._http.request(method, url, json=payload, headers=headers)
            except httpx.RequestError:
                if attempt == 2:
                    return DeliveryResult.failed(0, "NETWORK_ERROR")
                self._sleeper(0.25 * (2**attempt))
                continue
            if 200 <= response.status_code < 300:
                try:
                    message_id = response.json().get("id")
                except (TypeError, ValueError):
                    message_id = None
                if isinstance(message_id, str) and message_id:
                    return DeliveryResult(True, message_id, response.status_code)
                return DeliveryResult.failed(response.status_code, "INVALID_RESPONSE")
            if response.status_code != 429 and response.status_code < 500:
                return DeliveryResult.failed(response.status_code, f"HTTP_{response.status_code}")
            delay = 0.25 * (2**attempt)
            if response.status_code == 429:
                try:
                    delay = float(response.json()["retry_after"])
                except (KeyError, TypeError, ValueError):
                    return DeliveryResult.failed(429, "RATE_LIMIT_DEFERRED")
                if delay < 0 or delay > 5:
                    return DeliveryResult.failed(429, "RATE_LIMIT_DEFERRED")
            if attempt == 2:
                return DeliveryResult.failed(response.status_code, "RETRY_EXHAUSTED")
            self._sleeper(delay)
        return DeliveryResult.failed(0, "RETRY_EXHAUSTED")
