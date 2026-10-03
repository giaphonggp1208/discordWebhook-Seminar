from __future__ import annotations

from pathlib import Path

from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, MetaData, String, Table, create_engine, event
from sqlalchemy.engine import Engine

metadata = MetaData()

leave_requests = Table(
    "leave_requests", metadata,
    Column("id", String(50), primary_key=True),
    Column("from_date", Date, nullable=False),
    Column("to_date", Date, nullable=False),
    Column("reason", String(500), nullable=False),
    Column("status", String(16), nullable=False),
    Column("decided_by", String(50)),
    Column("decided_at", DateTime(timezone=True)),
    Column("message_id", String(50)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
processed_interactions = Table(
    "processed_interactions", metadata,
    Column("id", String(50), primary_key=True),
    Column("request_id", String(50), ForeignKey("leave_requests.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
activity_log = Table(
    "activity_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("request_id", String(50), ForeignKey("leave_requests.id"), nullable=False),
    Column("event", String(32), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
deliveries = Table(
    "deliveries", metadata,
    Column("id", String(36), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("aggregate_id", String(50), nullable=False),
    Column("status", String(16), nullable=False),
    Column("error", String(100)),
    Column("attempts", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def create_database(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def initialize_database(engine: Engine) -> None:
    metadata.create_all(engine)
