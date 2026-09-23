from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(ORMModel):
    items: list
    total: int
    limit: int
    offset: int
