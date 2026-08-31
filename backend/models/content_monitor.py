"""Domain models for content monitoring and statistical detection."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import TimestampMixin


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentAccount(TimestampMixin):
    """A monitored public account on a content platform."""

    __tablename__ = "content_accounts"
    __table_args__ = (
        UniqueConstraint(
            "platform", "external_account_id", name="uq_content_account_platform_external"
        ),
    )

    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    handle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    profile_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Optional OpenCLI binding used by the content workbench integration. ``source_id``
    # above remains the source that last produced data; this field is the
    # source configured for future巡检.
    collection_source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )
    collection_command: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    collection_args: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    collection_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collection_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="unconfigured"
    )
    last_collection_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    works: Mapped[list["ContentWork"]] = relationship(
        "ContentWork", back_populates="account", cascade="all, delete-orphan"
    )


class ContentWork(TimestampMixin):
    """A stable public work identity, independent from its changing metrics."""

    __tablename__ = "content_works"
    __table_args__ = (
        UniqueConstraint("account_id", "external_work_id", name="uq_content_work_account_external"),
        Index("ix_content_works_source_published", "source_id", "published_at"),
    )

    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("content_accounts.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )
    external_work_id: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at_raw: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    raw_identity: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    account: Mapped[ContentAccount] = relationship("ContentAccount", back_populates="works")
    snapshots: Mapped[list["EngagementSnapshot"]] = relationship(
        "EngagementSnapshot", back_populates="work", cascade="all, delete-orphan"
    )
    detections: Mapped[list["DetectionResult"]] = relationship(
        "DetectionResult", back_populates="work"
    )


class EngagementSnapshot(TimestampMixin):
    """Public interaction counters observed for a work at a point in time."""

    __tablename__ = "engagement_snapshots"
    __table_args__ = (
        UniqueConstraint("work_id", "task_id", name="uq_engagement_snapshot_work_task"),
        Index("ix_engagement_snapshots_work_collected", "work_id", "collected_at"),
    )

    work_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("content_works.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("collection_tasks.id", ondelete="SET NULL"), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    view_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    favorite_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    share_count: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    work: Mapped[ContentWork] = relationship("ContentWork", back_populates="snapshots")
    detections: Mapped[list["DetectionResult"]] = relationship(
        "DetectionResult", back_populates="snapshot", cascade="all, delete-orphan"
    )


class DetectionResult(TimestampMixin):
    """Deterministic evidence produced by the non-AI statistical detector."""

    __tablename__ = "detection_results"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "detector_version", name="uq_detection_snapshot_version"),
        Index("ix_detection_results_work_status", "work_id", "status"),
    )

    work_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("content_works.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("engagement_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    baseline_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relative_multiple: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hot_multiple: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    very_hot_multiple: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    enters_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    priority_analysis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    work: Mapped[ContentWork] = relationship("ContentWork", back_populates="detections")
    snapshot: Mapped[EngagementSnapshot] = relationship(
        "EngagementSnapshot", back_populates="detections"
    )
