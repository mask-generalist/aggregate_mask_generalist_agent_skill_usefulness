from pydantic import BaseModel
from typing import Optional


class AppDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    url: Optional[str] = None
