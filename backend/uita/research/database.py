"""Persistence declarations only. Schema installation belongs to Alembic."""

import os
import time
from contextlib import contextmanager

from sqlalchemy import (
    JSON,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "research_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(default=True)


class Session(Base):
    __tablename__ = "research_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    expires: Mapped[float] = mapped_column(Float)


class Run(Base):
    __tablename__ = "research_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="paused", index=True)
    owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fence: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    next_tick: Mapped[float] = mapped_column(Float, default=0)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Event(Base):
    __tablename__ = "research_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    clock: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON)


class Checkpoint(Base):
    __tablename__ = "research_checkpoints"
    __table_args__ = (UniqueConstraint("run_id", "revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[dict] = mapped_column(JSON)


class Command(Base):
    __tablename__ = "research_commands"
    key: Mapped[str] = mapped_column(String(250), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)


class Artifact(Base):
    __tablename__ = "research_artifacts"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    checksum: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class Budget(Base):
    __tablename__ = "research_budgets"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    cap: Mapped[float] = mapped_column(Float)
    reserved: Mapped[float] = mapped_column(Float, default=0)


class Reservation(Base):
    __tablename__ = "research_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    amount: Mapped[float] = mapped_column(Float)
    actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class Job(Base):
    __tablename__ = "research_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True, default="queued")
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    fence: Mapped[int] = mapped_column(Integer, default=0)


class Database:
    def __init__(self, url=None):
        url = url or os.environ.get("DATABASE_URL", "sqlite:///./uita-research.db")
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"check_same_thread": False, "timeout": 30}
            if url.startswith("sqlite")
            else {"connect_timeout": 15},
        )
        if self.engine.dialect.name == "postgresql":

            @event.listens_for(self.engine, "connect")
            def timeouts(connection, _):
                prior = connection.autocommit
                connection.autocommit = True
                connection.execute("SET statement_timeout = '30s'")
                connection.execute("SET lock_timeout = '10s'")
                connection.execute("SET idle_in_transaction_session_timeout = '30s'")
                connection.autocommit = prior

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        with self.sessions() as session:
            # SQLite's writer lock supplies the row-lock semantics used by local tests.
            if self.engine.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def close(self):
        self.engine.dispose()
