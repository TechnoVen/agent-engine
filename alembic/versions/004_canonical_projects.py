"""Canonical projects schema

Revision ID: 004_canonical_projects
Revises: 003_canonical_executions
Create Date: 2026-09-18 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004_canonical_projects"
down_revision: Union[str, None] = "003_canonical_executions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("root_path", sa.Text(), nullable=False, unique=True),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("is_default", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_projects_name", "projects", ["name"])
    op.create_index("idx_projects_is_default", "projects", ["is_default"])


def downgrade() -> None:
    op.drop_index("idx_projects_is_default", table_name="projects")
    op.drop_index("idx_projects_name", table_name="projects")
    op.drop_table("projects")
