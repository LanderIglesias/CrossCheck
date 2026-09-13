from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(validation_alias="DATABASE_URL")
    sec_user_agent: str = Field(validation_alias="SEC_USER_AGENT")
    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    hf_token: str | None = Field(default=None, validation_alias="HF_TOKEN")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"


settings = Settings()  # type: ignore[call-arg]
