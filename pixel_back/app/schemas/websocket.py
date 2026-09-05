from pydantic import BaseModel, ConfigDict, Field


class PixelPlaceData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    color: str
