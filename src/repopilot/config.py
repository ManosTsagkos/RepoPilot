from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: SecretStr | None = None
    github_token: SecretStr | None = None
    openai_model: str = Field(default="gpt-4.1-mini", min_length=1, max_length=100)
    request_timeout: float = Field(default=15, gt=0, le=120)
    llm_timeout: float = Field(default=45, gt=0, le=120)
    max_retries: int = Field(default=2, ge=0, le=3)
    cache_ttl: int = Field(default=900, ge=0, le=3600)

    @field_validator("openai_model", mode="before")
    @classmethod
    def trim_model(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("openai_api_key", "github_token", mode="before")
    @classmethod
    def empty_key(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value
