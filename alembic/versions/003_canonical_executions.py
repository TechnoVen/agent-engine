"""Canonical execution domain and event stream schema

Revision ID: 003_canonical_executions
Revises: 002_unified_session_store
Create Date: 2026-09-18 19:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "003_canonical_executions"
down_revision: Union[str, None] = "002_unified_session_store"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. executions table
    op.create_table(
        "executions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("sessions.session_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("routing_tier", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_cost_estimated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_executions_project", "executions", ["project_id"])
    op.create_index("idx_executions_session", "executions", ["session_id"])
    op.create_index("idx_executions_status", "executions", ["status"])

    # 2. execution_events table
    op.create_table(
        "execution_events",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "execution_id",
            sa.Text(),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_num", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("execution_id", "sequence_num", name="uq_execution_events_seq"),
    )
    op.create_index("idx_events_execution", "execution_events", ["execution_id"])


def downgrade() -> None:
    op.drop_index("idx_events_execution", table_name="execution_events")
    op.drop_table("execution_events")

    op.drop_index("idx_executions_status", table_name="executions")
    op.drop_index("idx_executions_session", table_name="executions")
    op.drop_index("idx_executions_project", table_name="executions")
    op.drop_table("executions")
