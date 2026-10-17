"""Frozen additive research schema; historical source tables are untouched."""

import sqlalchemy as sa
from alembic import op

revision = "0001_research"
down_revision = None


def upgrade():
    op.create_table(
        "research_artifacts",
        sa.Column("id", sa.String(200), nullable=False, primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False, primary_key=False),
        sa.Column("checksum", sa.String(64), nullable=False, primary_key=False),
        sa.Column("payload", sa.JSON(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_research_artifacts_kind", "research_artifacts", ["kind"], unique=False
    )
    op.create_table(
        "research_budgets",
        sa.Column("id", sa.String(200), nullable=False, primary_key=True),
        sa.Column("cap", sa.Float(), nullable=False, primary_key=False),
        sa.Column("reserved", sa.Float(), nullable=False, primary_key=False),
    )
    op.create_table(
        "research_checkpoints",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("state", sa.JSON(), nullable=False, primary_key=False),
        sa.UniqueConstraint("run_id", "revision"),
    )
    op.create_index(
        "ix_research_checkpoints_run_id",
        "research_checkpoints",
        ["run_id"],
        unique=False,
    )
    op.create_table(
        "research_commands",
        sa.Column("key", sa.String(250), nullable=False, primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, primary_key=False),
        sa.Column("response", sa.JSON(), nullable=False, primary_key=False),
    )
    op.create_table(
        "research_events",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("clock", sa.Float(), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(50), nullable=False, primary_key=False),
        sa.Column("payload", sa.JSON(), nullable=False, primary_key=False),
        sa.UniqueConstraint("run_id", "sequence"),
    )
    op.create_index(
        "ix_research_events_run_id", "research_events", ["run_id"], unique=False
    )
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("team", sa.String(100), nullable=False, primary_key=False),
        sa.Column("status", sa.String(24), nullable=False, primary_key=False),
        sa.Column("payload", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("result", sa.JSON(), nullable=True, primary_key=False),
        sa.Column("owner", sa.String(36), nullable=True, primary_key=False),
        sa.Column("lease_until", sa.Float(), nullable=False, primary_key=False),
        sa.Column("fence", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_research_jobs_status", "research_jobs", ["status"], unique=False
    )
    op.create_index("ix_research_jobs_team", "research_jobs", ["team"], unique=False)
    op.create_table(
        "research_reservations",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("amount", sa.Float(), nullable=False, primary_key=False),
        sa.Column("actual", sa.Float(), nullable=True, primary_key=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_research_reservations_run_id",
        "research_reservations",
        ["run_id"],
        unique=False,
    )
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("team", sa.String(100), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("state", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(24), nullable=False, primary_key=False),
        sa.Column("owner", sa.String(36), nullable=True, primary_key=False),
        sa.Column("fence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("lease_until", sa.Float(), nullable=False, primary_key=False),
        sa.Column("next_tick", sa.Float(), nullable=False, primary_key=False),
        sa.Column("created", sa.Float(), nullable=False, primary_key=False),
    )
    op.create_index("ix_research_runs_team", "research_runs", ["team"], unique=False)
    op.create_index(
        "ix_research_runs_status", "research_runs", ["status"], unique=False
    )
    op.create_table(
        "research_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False, primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("expires", sa.Float(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_research_sessions_user_id", "research_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "research_users",
        sa.Column("id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("team", sa.String(100), nullable=False, primary_key=False),
        sa.Column("username", sa.String(100), nullable=False, primary_key=False),
        sa.Column("password_hash", sa.Text(), nullable=False, primary_key=False),
        sa.Column("role", sa.String(20), nullable=False, primary_key=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, primary_key=False),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_research_users_team", "research_users", ["team"], unique=False)


def downgrade():
    raise RuntimeError(
        "Destructive downgrade disabled. Roll back application code; preserve research evidence."
    )
