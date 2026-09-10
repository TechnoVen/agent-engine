"""Initial schema baseline for Agent Engine repository

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. audit_patches
    op.create_table(
        "audit_patches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("patch_type", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.Text(), nullable=True),
        sa.Column("report", sa.Text(), nullable=True),
        sa.Column("original_code", sa.Text(), nullable=True),
        sa.Column("patched_code", sa.Text(), nullable=True),
    )
    op.create_index("idx_audit_patches_status", "audit_patches", ["status"])

    # 2. sessions
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("messages", sa.Text(), nullable=False, server_default="[]"),
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id"])

    # 3. users
    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="developer"),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("idx_users_tenant", "users", ["tenant_id"])

    # 4. policies
    op.create_table(
        "policies",
        sa.Column("policy_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("rules", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )

    # 5. cost_records
    op.create_table(
        "cost_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=True),
        sa.Column("success", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("idx_cost_agent", "cost_records", ["agent_name"])
    op.create_index("idx_cost_model", "cost_records", ["model_name"])

    # 6. benchmarks
    op.create_table(
        "benchmarks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("cost_per_success", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("idx_benchmarks_task", "benchmarks", ["task_type"])


def downgrade() -> None:
    op.drop_table("benchmarks")
    op.drop_table("cost_records")
    op.drop_table("policies")
    op.drop_table("users")
    op.drop_table("sessions")
    op.drop_table("audit_patches")
