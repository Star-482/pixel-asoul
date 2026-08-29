from pydantic import BaseModel, Field


class CanvasEvent(BaseModel):
    event_id: int
    x: int
    y: int
    color: str
    source: str


class CanvasEventsResponse(BaseModel):
    events: list[CanvasEvent]
    head_event_id: int
    has_more: bool


class SessionResponse(BaseModel):
    visitor_id: str
    expires_in_days: int = Field(ge=1)
