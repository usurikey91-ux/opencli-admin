"""add content monitor tables

Revision ID: m3n4o5p6q7r8
Revises: l2g3h4i5j6k7
Create Date: 2026-08-24

"""

from alembic import op
import sqlalchemy as sa


revision = "m3n4o5p6q7r8"
down_revision = "l2g3h4i5j6k7"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "content_accounts",
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("data_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("external_account_id", sa.String(255), nullable=False),
        sa.Column("handle", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("raw_profile", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform", "external_account_id", name="uq_content_account_platform_external"
        ),
    )

    op.create_table(
        "content_works",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("content_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("data_sources.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_work_id", sa.String(512), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at_raw", sa.String(255), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_identity", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "external_work_id", name="uq_content_work_account_external"
        ),
    )
    op.create_index(
        "ix_content_works_source_published", "content_works", ["source_id", "published_at"]
    )

    op.create_table(
        "engagement_snapshots",
        sa.Column(
            "work_id",
            sa.String(36),
            sa.ForeignKey("content_works.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("collection_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.BigInteger(), nullable=True),
        sa.Column("favorite_count", sa.BigInteger(), nullable=True),
        sa.Column("share_count", sa.BigInteger(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_id", "task_id", name="uq_engagement_snapshot_work_task"),
    )
    op.create_index(
        "ix_engagement_snapshots_work_collected",
        "engagement_snapshots",
        ["work_id", "collected_at"],
    )

    op.create_table(
        "detection_results",
        sa.Column(
            "work_id",
            sa.String(36),
            sa.ForeignKey("content_works.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("engagement_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("detector_version", sa.String(64), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("current_value", sa.BigInteger(), nullable=True),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("baseline_size", sa.Integer(), nullable=False),
        sa.Column("relative_multiple", sa.Float(), nullable=True),
        sa.Column("hot_multiple", sa.Float(), nullable=False),
        sa.Column("very_hot_multiple", sa.Float(), nullable=False),
        sa.Column("enters_analysis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("priority_analysis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "detector_version", name="uq_detection_snapshot_version"
        ),
    )
    op.create_index(
        "ix_detection_results_work_status", "detection_results", ["work_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_detection_results_work_status", table_name="detection_results")
    op.drop_table("detection_results")
    op.drop_index(
        "ix_engagement_snapshots_work_collected", table_name="engagement_snapshots"
    )
    op.drop_table("engagement_snapshots")
    op.drop_index("ix_content_works_source_published", table_name="content_works")
    op.drop_table("content_works")
    op.drop_table("content_accounts")
