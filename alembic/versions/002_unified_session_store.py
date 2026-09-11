"""Unified session store schema expansion

Revision ID: 002_unified_session_store
Revises: 001_initial_schema
Create Date: 2026-09-10 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002_unified_session_store"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add unified session columns to sessions table
    op.add_column(
        "sessions", sa.Column("title", sa.Text(), nullable=False, server_default="Untitled Session")
    )
    op.add_column(
        "sessions", sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default")
    )
    op.add_column("sessions", sa.Column("channel", sa.Text(), nullable=False, server_default="web"))
    op.add_column(
        "sessions", sa.Column("status", sa.Text(), nullable=False, server_default="active")
    )
    op.add_column("sessions", sa.Column("parent_session_id", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("fork_point_message_id", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=True))

    op.create_index("idx_sessions_tenant", "sessions", ["tenant_id"])
    op.create_index("idx_sessions_status", "sessions", ["status"])
    op.create_index("idx_sessions_parent", "sessions", ["parent_session_id"])


def downgrade() -> None:
    op.drop_index("idx_sessions_parent", table_name="sessions")
    op.drop_index("idx_sessions_status", table_name="sessions")
    op.drop_index("idx_sessions_tenant", table_name="sessions")

    op.drop_column("sessions", "summary")
    op.drop_column("sessions", "fork_point_message_id")
    op.drop_column("sessions", "parent_session_id")
    op.drop_column("sessions", "status")
    op.drop_column("sessions", "channel")
    op.drop_column("sessions", "tenant_id")
    op.drop_column("sessions", "title")
