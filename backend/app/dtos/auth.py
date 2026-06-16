from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str = Field(min_length=1, max_length=72)  # bcrypt усекает >72 байт


class UserDTO(BaseModel):
    id: int
    username: str
    role: str


class UserAdminDTO(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime


class LoginResponse(BaseModel):
    ok: bool = True
    user: UserDTO
