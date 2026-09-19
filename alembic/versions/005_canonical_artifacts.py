"""Canonical artifacts schema

Revision ID: 005_canonical_artifacts
Revises: 004_canonical_projects
Create Date: 2026-09-19 21:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "005_canonical_artifacts"
down_revision: Union[str, None] = "004_canonical_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "execution_id",
            sa.Text(),
            sa.ForeignKey("executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False, server_default="file"),
        sa.Column(
            "mime_type", sa.Text(), nullable=False, server_default="application/octet-stream"
        ),
        sa.Column("storage_kind", sa.Text(), nullable=False, server_default="filesystem"),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("inline_content", sa.Text(), nullable=True),
        sa.Column("sha256_hash", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ready"),
        sa.Column("lineage_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.Text(), nullable=True),
    )
    op.create_index("idx_artifacts_project", "artifacts", ["project_id"])
    op.create_index("idx_artifacts_execution", "artifacts", ["execution_id"])
    op.create_index("idx_artifacts_type", "artifacts", ["type"])
    op.create_index("idx_artifacts_status", "artifacts", ["status"])


def downgrade() -> None:
    op.drop_index("idx_artifacts_status", table_name="artifacts")
    op.drop_index("idx_artifacts_type", table_name="artifacts")
    op.drop_index("idx_artifacts_execution", table_name="artifacts")
    op.drop_index("idx_artifacts_project", table_name="artifacts")
    op.drop_table("artifacts")
