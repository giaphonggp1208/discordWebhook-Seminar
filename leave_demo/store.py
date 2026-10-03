from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, insert, select, update
from sqlalchemy.engine import Engine

from .database import activity_log, deliveries, leave_requests, processed_interactions


class NotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LeaveRequest:
    id: str
    from_date: date
    to_date: date
    reason: str
    status: str
    decided_by: str | None
    decided_at: datetime | None
    message_id: str | None
    created_at: datetime

    def api(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "fromDate": self.from_date.isoformat(),
            "toDate": self.to_date.isoformat(),
            "reason": self.reason,
            "status": self.status,
            "decidedBy": self.decided_by,
            "decidedAt": _timestamp(self.decided_at),
            "messageId": self.message_id,
            "createdAt": _timestamp(self.created_at),
        }


@dataclass(frozen=True, slots=True)
class Delivery:
    id: str
    kind: str
    aggregate_id: str
    status: str
    error: str | None
    attempts: int
    created_at: datetime

    def api(self) -> dict[str, str | int | None]:
        return {
            "id": self.id,
            "kind": self.kind,
            "aggregateId": self.aggregate_id,
            "status": self.status,
            "error": self.error,
            "attempts": self.attempts,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _leave(row) -> LeaveRequest:  # type: ignore[no-untyped-def]
    return LeaveRequest(**dict(row._mapping))


def _delivery(row) -> Delivery:  # type: ignore[no-untyped-def]
    return Delivery(**dict(row._mapping))


class LeaveStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_requests(self) -> list[LeaveRequest]:
        with self._engine.connect() as connection:
            return [_leave(row) for row in connection.execute(select(leave_requests).order_by(leave_requests.c.created_at.desc()))]

    def get(self, request_id: str) -> LeaveRequest:
        with self._engine.connect() as connection:
            row = connection.execute(select(leave_requests).where(leave_requests.c.id == request_id)).first()
        if row is None:
            raise NotFoundError
        return _leave(row)

    def create(self, from_date: date, to_date: date, reason: str) -> LeaveRequest:
        request_id, now = f"LR-{uuid4()}", _now()
        with self._engine.begin() as connection:
            connection.execute(insert(leave_requests).values(
                id=request_id, from_date=from_date, to_date=to_date, reason=reason,
                status="PENDING", created_at=now,
            ))
            self._activity(connection, request_id, "CREATED", "demo", now)
            self._enqueue(connection, "APPROVAL", request_id, now)
            self._enqueue(connection, "ACTIVITY_CREATED", request_id, now)
        return self.get(request_id)

    def decide(self, request_id: str, action: str, actor: str, message_id: str, interaction_id: str) -> str:
        if action not in {"approve", "reject"}:
            return "Thao tác không hợp lệ."
        now, status = _now(), "APPROVED" if action == "approve" else "REJECTED"
        # BEGIN IMMEDIATE serializes competing SQLite writers before conditional transition.
        with self._engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                row = connection.execute(select(leave_requests).where(leave_requests.c.id == request_id)).first()
                if row is None:
                    raise NotFoundError
                request = _leave(row)
                if request.message_id != message_id:
                    connection.commit()
                    return "Tin nhắn không khớp với đơn."
                duplicate = connection.execute(
                    select(processed_interactions.c.id).where(processed_interactions.c.id == interaction_id)
                ).first()
                if duplicate:
                    connection.commit()
                    return "Thao tác này đã được xử lý."
                changed = connection.execute(
                    update(leave_requests)
                    .where(and_(
                        leave_requests.c.id == request_id,
                        leave_requests.c.status == "PENDING",
                        leave_requests.c.message_id == message_id,
                    ))
                    .values(status=status, decided_by=actor, decided_at=now)
                ).rowcount
                if changed != 1:
                    current = self._get_in_transaction(connection, request_id)
                    connection.commit()
                    return f"Đơn đã có quyết định: {current.status}"
                connection.execute(insert(processed_interactions).values(id=interaction_id, request_id=request_id, created_at=now))
                self._activity(connection, request_id, status, actor, now)
                self._enqueue(connection, "UPDATE_APPROVAL", request_id, now)
                self._enqueue(connection, "ACTIVITY_DECIDED", request_id, now)
                connection.commit()
                return f"Đơn {request_id}: {status}"
            except Exception:
                connection.rollback()
                raise

    def deliveries(self) -> list[Delivery]:
        with self._engine.connect() as connection:
            return [_delivery(row) for row in connection.execute(select(deliveries).order_by(deliveries.c.created_at.desc()))]

    def pending_deliveries(self, limit: int = 10) -> list[Delivery]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(deliveries)
                .where(deliveries.c.status == "PENDING")
                .order_by(deliveries.c.created_at.asc())
                .limit(limit)
            )
            return [_delivery(row) for row in rows]

    def activities(self) -> list[dict[str, str | None]]:
        with self._engine.connect() as connection:
            rows = connection.execute(select(activity_log).order_by(activity_log.c.id.desc()).limit(100))
            return [
                {
                    "REQUEST_ID": row.request_id,
                    "EVENT": row.event,
                    "ACTOR": row.actor,
                    "CREATED_AT": _timestamp(row.created_at),
                }
                for row in rows
            ]

    def enqueue(self, kind: str, aggregate_id: str) -> None:
        with self._engine.begin() as connection:
            self._enqueue(connection, kind, aggregate_id, _now())

    def claim(self, delivery_id: str) -> bool:
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(deliveries)
                .where(and_(deliveries.c.id == delivery_id, deliveries.c.status == "PENDING"))
                .values(status="RUNNING", attempts=deliveries.c.attempts + 1)
            ).rowcount
        return changed == 1

    def sent(self, delivery: Delivery, message_id: str | None) -> None:
        with self._engine.begin() as connection:
            if delivery.kind == "APPROVAL":
                if not message_id:
                    raise ValueError("approval delivery requires a Discord message id")
                connection.execute(update(leave_requests).where(leave_requests.c.id == delivery.aggregate_id).values(message_id=message_id))
            connection.execute(update(deliveries).where(deliveries.c.id == delivery.id).values(status="SENT", error=None))

    def failed(self, delivery_id: str, error: str) -> None:
        with self._engine.begin() as connection:
            connection.execute(update(deliveries).where(deliveries.c.id == delivery_id).values(status="FAILED", error=error))

    def retry(self, delivery_id: str) -> bool:
        with self._engine.begin() as connection:
            changed = connection.execute(
                update(deliveries)
                .where(and_(deliveries.c.id == delivery_id, deliveries.c.status == "FAILED"))
                .values(status="PENDING", error=None)
            ).rowcount
        return changed == 1

    def recover_interrupted(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                update(deliveries)
                .where(deliveries.c.status == "RUNNING")
                .values(status="FAILED", error="INTERRUPTED_DELIVERY_REVIEW_BEFORE_RETRY")
            )

    @staticmethod
    def _activity(connection, request_id: str, event: str, actor: str, created_at: datetime) -> None:  # type: ignore[no-untyped-def]
        connection.execute(insert(activity_log).values(request_id=request_id, event=event, actor=actor, created_at=created_at))

    @staticmethod
    def _enqueue(connection, kind: str, aggregate_id: str, created_at: datetime) -> None:  # type: ignore[no-untyped-def]
        connection.execute(insert(deliveries).values(
            id=str(uuid4()), kind=kind, aggregate_id=aggregate_id, status="PENDING", attempts=0, created_at=created_at,
        ))

    @staticmethod
    def _get_in_transaction(connection, request_id: str) -> LeaveRequest:  # type: ignore[no-untyped-def]
        row = connection.execute(select(leave_requests).where(leave_requests.c.id == request_id)).first()
        if row is None:
            raise NotFoundError
        return _leave(row)
