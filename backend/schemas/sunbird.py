from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.common import UTCModel


class SunbirdAccountBindRequest(BaseModel):
    platform: str = Field(min_length=1, max_length=64)
    external_account_id: str = Field(min_length=1, max_length=255)
    handle: str | None = None
    display_name: str | None = None
    profile_url: str | None = None
    source_id: str | None = None
    command: str | None = Field(None, max_length=255)
    args: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SunbirdAccountRead(UTCModel):
    id: str
    platform: str
    external_account_id: str
    handle: str | None = None
    display_name: str | None = None
    profile_url: str | None = None
    collection_source_id: str | None = None
    collection_command: str | None = None
    collection_args: dict[str, Any]
    collection_enabled: bool
    collection_status: str
    last_collection_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None

    model_config = {"from_attributes": True}


class SunbirdCheckRead(BaseModel):
    account_id: str
    task_id: str
    status: str
    source_id: str


class SunbirdWorkRead(BaseModel):
    account: dict[str, Any]
    platform: str
    external_work_id: str
    url: str | None = None
    title: str | None = None
    content: str | None = None
    published_at: datetime | None = None
    latest_public_metrics: dict[str, Any]
    final_public_metrics: dict[str, Any]
    relative_multiple: float | None = None
    status: str
    priority: bool
    evidence: dict[str, Any]
