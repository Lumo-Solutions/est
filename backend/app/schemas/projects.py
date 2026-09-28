from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ProjectCreate(BaseModel):
    code: str
    name: str
    client_name: str | None = None
    tender_ref: str | None = None
    base_currency: str = "AED"


class ProjectOut(ORMModel):
    id: UUID
    code: str
    name: str
    client_name: str | None
    status: str
    tender_ref: str | None
    base_currency: str
    emirate: str | None
    area: str | None
    latitude: float | None
    longitude: float | None
    created_at: datetime


class ProjectMemberAdd(BaseModel):
    user_id: UUID
    project_role: str | None = None


class ProjectMemberOut(ORMModel):
    user_id: UUID
    project_role: str | None


class ProjectLocationUpdate(BaseModel):
    emirate: str | None = None
    area: str | None = None
    latitude: float | None = None
    longitude: float | None = None
