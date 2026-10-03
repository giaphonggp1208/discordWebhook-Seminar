from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    success: bool
    message_id: str | None = None
    http_status: int = 0
    error: str | None = None

    @classmethod
    def failed(cls, http_status: int, error: str) -> "DeliveryResult":
        return cls(False, None, http_status, error)


@dataclass(frozen=True, slots=True)
class DiscordMessageRef:
    channel_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    destination: str
    title: str
    content: str
    fields: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.destination.strip() or not self.title.strip():
            raise ValueError("destination and title are required")
        if len(self.title) > 256 or len(self.content) > 2000:
            raise ValueError("message exceeds Discord limits")
        if len(self.fields) > 25:
            raise ValueError("embed exceeds Discord limits")
        total = len(self.title)
        for name, value in self.fields.items():
            if not name.strip() or not value.strip() or len(name) > 256 or len(value) > 1024:
                raise ValueError("embed exceeds Discord limits")
            total += len(name) + len(value)
        if total > 6000:
            raise ValueError("embed exceeds Discord limits")

    @classmethod
    def activity(cls, content: str) -> "NotificationMessage":
        return cls("activity", "Activity", content)


@dataclass(frozen=True, slots=True)
class ApprovalMessage:
    channel_id: str
    content: str
    approve_id: str
    reject_id: str

    def __post_init__(self) -> None:
        if (
            not self.channel_id.isdecimal()
            or len(self.content) > 2000
            or not self.approve_id.strip()
            or len(self.approve_id) > 100
            or not self.reject_id.strip()
            or len(self.reject_id) > 100
        ):
            raise ValueError("invalid approval message")
