from pydantic import BaseModel


class RoomResponse(BaseModel):
    id: str
    code: str
    active: bool
