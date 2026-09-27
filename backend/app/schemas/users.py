from __future__ import annotations

from app.schemas.common import ORMModel


class UserOut(ORMModel):
    id: str
    username: str
    email: str | None
    enabled: bool
    roles: list[str]
