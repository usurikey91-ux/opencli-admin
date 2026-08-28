from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.schemas.common import UTCModel


class ContentAccountImportItem(BaseModel):
    platform: str = Field(min_length=1, max_length=64)
    external_account_id: str = Field(min_length=1, max_length=255)
    handle: Optional[str] = None
    display_name: Optional[str] = None
    profile_url: Optional[str] = None


class ContentAccountImportRequest(BaseModel):
    items: list[ContentAccountImportItem] = Field(min_length=1, max_length=500)


class ContentAccountLinkImportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class ContentAccountRead(UTCModel):
    id: str
    source_id: Optional[str] = None
    platform: str
    external_account_id: str
    handle: Optional[str] = None
    display_name: Optional[str] = None
    profile_url: Optional[str] = None
    raw_profile: dict
    collection_source_id: Optional[str] = None
    collection_command: Optional[str] = None
    collection_args: dict[str, Any] = Field(default_factory=dict)
    collection_enabled: bool = False
    collection_status: str = "unconfigured"
    last_collection_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None

    model_config = {"from_attributes": True}
