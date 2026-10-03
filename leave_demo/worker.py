from __future__ import annotations

from discord_integration import ApprovalMessage, DeliveryResult, DiscordClient, DiscordMessageRef, NotificationMessage

from .config import Settings
from .store import Delivery, LeaveRequest, LeaveStore, NotFoundError


class DeliveryWorker:
    def __init__(self, store: LeaveStore, discord: DiscordClient, settings: Settings) -> None:
        self._store = store
        self._discord = discord
        self._settings = settings

    def tick(self) -> None:
        for job in self._store.pending_deliveries(limit=10):
            self.deliver(job)

    def deliver(self, job: Delivery) -> None:
        if not self._store.claim(job.id):
            return
        try:
            result = self._send(job)
            if result.success:
                self._store.sent(job, result.message_id)
            else:
                self._store.failed(job.id, result.error or "DELIVERY_ERROR")
        except Exception:
            # Transport internals can contain credentials, so only persist a categorical error.
            self._store.failed(job.id, "DELIVERY_ERROR")

    def _send(self, job: Delivery) -> DeliveryResult:
        if job.kind == "ALERT":
            return self._discord.send(NotificationMessage(
                "alerts", "System Alert", "Lỗi thử nghiệm đã được ghi nhận.",
                {"Service": "leave-service", "Error": "DEMO_FAILURE", "Correlation ID": job.aggregate_id},
            ))
        if job.kind == "DEPLOYMENT":
            return self._discord.send(NotificationMessage(
                "deployments", "Deployment Notification", "Demo deployment thành công!",
                {"Environment": "demo", "Version": "demo-v1", "Service": "leave-service"},
            ))
        if job.kind == "ACTIVITY_DEMO":
            return self._discord.send(NotificationMessage(
                "activity", "Activity Log", "Demo activity notification.",
                {"Event": "DEMO_EVENT", "Correlation ID": job.aggregate_id},
            ))
        leave = self._store.get(job.aggregate_id)
        if job.kind == "APPROVAL":
            if not self._settings.discord_configured:
                return DeliveryResult.failed(0, "NOT_CONFIGURED")
            return self._discord.send_approval(self._approval_message(leave))
        if job.kind == "UPDATE_APPROVAL":
            if not leave.message_id:
                return DeliveryResult.failed(0, "MISSING_APPROVAL_MESSAGE")
            return self._discord.finish_approval(
                DiscordMessageRef(self._settings.discord_approval_channel_id, leave.message_id),
                self._approval_message(leave),
            )
        event = "CREATED" if job.kind == "ACTIVITY_CREATED" else leave.status
        return self._discord.send(NotificationMessage(
            "activity", "Leave activity", f"Đơn {leave.id}: {event}",
            {"Request ID": leave.id, "Event": event},
        ))

    def _approval_message(self, leave: LeaveRequest) -> ApprovalMessage:
        status = {"APPROVED": "Đã duyệt", "REJECTED": "Từ chối"}.get(leave.status, "Chờ duyệt")
        content = (
            "Người gửi đơn: Nhân viên mẫu\n"
            f"Mã đơn: {leave.id}\n"
            f"Nghỉ từ: {leave.from_date:%d/%m/%Y} đến {leave.to_date:%d/%m/%Y}\n"
            f"Lý do: {leave.reason}\n"
            f"Trạng thái: {status}"
        )
        return ApprovalMessage(
            self._settings.discord_approval_channel_id,
            content,
            f"leave:{leave.id}:approve",
            f"leave:{leave.id}:reject",
        )
