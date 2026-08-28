"""add Sunbird collection binding fields to content accounts"""

import sqlalchemy as sa
from alembic import op

revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_accounts") as batch_op:
        batch_op.add_column(sa.Column("collection_source_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("collection_command", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column("collection_args", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )
        batch_op.add_column(
            sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column(
                "collection_status", sa.String(50), nullable=False, server_default="unconfigured"
            )
        )
        batch_op.add_column(
            sa.Column("last_collection_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error_code", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("last_error_message", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_content_accounts_collection_source",
            "data_sources",
            ["collection_source_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("content_accounts") as batch_op:
        batch_op.drop_constraint("fk_content_accounts_collection_source", type_="foreignkey")
        for name in (
            "last_error_message",
            "last_error_code",
            "last_success_at",
            "last_collection_at",
            "collection_status",
            "collection_enabled",
            "collection_args",
            "collection_command",
            "collection_source_id",
        ):
            batch_op.drop_column(name)
