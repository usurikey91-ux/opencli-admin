from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from backend.schemas.common import UTCModel


class ContentSnapshotRead(UTCModel):
    id: str
    collected_at: datetime
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    favorite_count: Optional[int] = None
    share_count: Optional[int] = None
    metrics: dict[str, Any]

    model_config = {"from_attributes": True}

class DetectionRead(UTCModel):
    id: str
    detector_version: str
    metric_name: str
    current_value: Optional[int] = None
    baseline_value: Optional[float] = None
    baseline_size: int
    baseline_missing_count: int
    relative_multiple: Optional[float] = None
    hot_multiple: float
    very_hot_multiple: float
    enters_analysis: bool
    priority_analysis: bool
    status: str
    evidence: dict[str, Any]
    evaluated_at: datetime

    model_config = {"from_attributes": True}


class MonitoredWorkRead(UTCModel):
    id: str
    account_id: str
    platform: str
    account_handle: Optional[str] = None
    account_display_name: Optional[str] = None
    external_work_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    first_seen_at: datetime
    last_seen_at: datetime
    status: str
    latest_snapshot: Optional[ContentSnapshotRead] = None
    detection: Optional[DetectionRead] = None
