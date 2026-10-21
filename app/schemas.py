from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import LeadStatus, Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.agent


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool


class LeadCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    source: str = Field(default="web", max_length=60)
    campaign: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def require_contact(self):
        if not self.email and not self.phone:
            raise ValueError("A lead needs at least an email or a phone number")
        return self


class LeadUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=40)
    campaign: str | None = Field(default=None, max_length=80)


class StatusChange(BaseModel):
    status: LeadStatus
    note: str | None = Field(default=None, max_length=1000)


class AssignLead(BaseModel):
    user_id: int


class NoteCreate(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    message: str
    user_id: int | None
    created_at: datetime


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str | None
    phone: str | None
    source: str
    campaign: str | None
    status: LeadStatus
    assigned_to_id: int | None
    created_at: datetime
    updated_at: datetime


class LeadDetail(LeadOut):
    activities: list[ActivityOut] = []


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int
    page: int
    size: int


class PipelineStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_source: dict[str, int]
    conversion_rate: float
