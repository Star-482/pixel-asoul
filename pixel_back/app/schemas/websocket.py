from pydantic import BaseModel, ConfigDict, Field


class PixelPlaceData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    color: str


class ChallengeVerifyData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge_id: str = Field(min_length=1, max_length=64)
    ticket: str = Field(min_length=1, max_length=4096)
    randstr: str = Field(min_length=1, max_length=1024)
