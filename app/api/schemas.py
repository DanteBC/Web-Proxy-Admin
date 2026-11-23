from datetime import datetime
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class ProxyUserCreate(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)
    enabled: bool = True
    max_bytes: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None


class ProxyUserUpdate(BaseModel):
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    enabled: bool | None = None
    max_bytes: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None


class RouteRuleCreate(BaseModel):
    cidr: str
    kind: str
    comment: str | None = None
    enabled: bool = True
