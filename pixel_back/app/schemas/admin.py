from pydantic import BaseModel, ConfigDict, Field


class AdminLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=1, max_length=512)


class ReadOnlyChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
