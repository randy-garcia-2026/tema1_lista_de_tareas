from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Status(str, Enum):
    pending = "pending"
    done = "done"


class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("el título no puede estar vacío")
        return v.strip()


class TodoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: Status | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("el título no puede estar vacío")
        return v.strip() if v else v


class Todo(BaseModel):
    id: int
    title: str
    description: str | None
    status: Status
