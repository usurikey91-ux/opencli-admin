from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.schemas.common import UTCModel


class SunbirdMonitoringRules(BaseModel):
    reference_work_count: int = Field(20, ge=5, le=50)
    hot_multiple: float = Field(3.0, ge=1.5, le=10.0)
    very_hot_multiple: float = Field(5.0, ge=2.0, le=20.0)
    interval_hours: int = Field(4)
    inherit_global: bool = True

    @model_validator(mode="after")
    def validate_rules(self):
        if self.interval_hours not in {1, 2, 4, 8, 12, 24}:
            raise ValueError("interval_hours must be one of 1, 2, 4, 8, 12, 24")
        if self.very_hot_multiple <= self.hot_multiple:
            raise ValueError("very_hot_multiple must be greater than hot_multiple")
        return self


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
    monitoring_rules: SunbirdMonitoringRules | None = None


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
    monitoring_rules: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class SunbirdAccountUpdateRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=255)
    monitoring_rules: SunbirdMonitoringRules | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if self.display_name is None and self.monitoring_rules is None and self.enabled is None:
            raise ValueError("display_name, monitoring_rules or enabled is required")
        return self


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
