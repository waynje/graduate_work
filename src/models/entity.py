from pydantic import BaseModel, Field


class UserEntity(BaseModel):
    id: str
    login: str = Field(min_length=3, max_length=255)
    is_active: bool = True
    is_superuser: bool = False