from typing import Optional,  Literal

from pydantic import BaseModel, Field, model_validator


Region = Literal["global", "eu"]


class ConfigWrite(BaseModel):
    model_config = {"extra": "forbid"}

    region: Region
    user_token: str = Field(min_length=8, max_length=4096)
    project_uuid: str = Field(min_length=6, max_length=128)
    workflow_uuid: str = Field(min_length=6, max_length=128)
    creator_id: Optional[str] = Field(default=None, max_length=128)


class StoredFH2Config(ConfigWrite):
    pass


class ConfigStatus(BaseModel):
    region: Optional[Region] = None
    token_configured: bool = False
    project_uuid_suffix: Optional[str] = None
    workflow_uuid_suffix: Optional[str] = None
    creator_id_suffix: Optional[str] = None


IncidentType = Literal[
    "Security Alarm",
    "Fire",
    "Traffic Accident",
    "Crime in Progress",
    "Search & Rescue",
    "Missing Person",
    "Other",
]


class DispatchRequest(BaseModel):
    model_config = {"extra": "forbid"}

    incident_id: str = Field(pattern=r"^INC-[A-Z0-9-]{6,40}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    priority: int = Field(default=5, ge=1, le=5)
    incident_type: Optional[IncidentType] = None
    custom_incident_type: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = Field(default=None, max_length=2000)
    location: Optional[str] = Field(default=None, max_length=300)
    operator_name: Optional[str] = Field(default=None, max_length=120)
    caller_phone: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_other(self):
        if self.incident_type == "Other" and not self.custom_incident_type:
            raise ValueError("custom_incident_type is required for Other")
        if self.incident_type != "Other" and self.custom_incident_type:
            raise ValueError("custom_incident_type requires Other")
        return self


class FH2Response(BaseModel):
    outcome: Literal["success", "failure", "indeterminate"]
    http_status: Optional[int] = None
    body: Optional[object] = None
    error_category: Optional[str] = None


class DispatchResult(FH2Response):
    incident_id: str
    audit_id: str
    replayed: bool = False


class GeocodeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200)


class GeocodeResponse(BaseModel):
    latitude: float
    longitude: float
    display_name: str
