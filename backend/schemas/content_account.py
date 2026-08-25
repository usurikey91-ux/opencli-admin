from typing import Optional

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


class ContentAccountRead(UTCModel):
    id: str
    source_id: Optional[str] = None
    platform: str
    external_account_id: str
    handle: Optional[str] = None
    display_name: Optional[str] = None
    profile_url: Optional[str] = None
    raw_profile: dict

    model_config = {"from_attributes": True}
