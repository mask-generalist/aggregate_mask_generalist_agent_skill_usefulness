from pydantic import BaseModel


class Alert(BaseModel):
    message: str
