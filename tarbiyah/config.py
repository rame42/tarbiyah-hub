"""Static configuration: paths and secrets, read from environment / .env.

Operational settings that users change from the dashboard (operating hours,
limits, concurrency...) live in the database instead; see tarbiyah.settings.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = Field(default=PROJECT_ROOT / "data", alias="TH_DATA_DIR")
    database_url: str | None = Field(default=None, alias="TH_DATABASE_URL")
    contact_email: str = Field(default="", alias="TH_CONTACT_EMAIL")
    user_agent: str = Field(
        default="TarbiyahHub/0.1 (research crawler; respects robots.txt)", alias="TH_USER_AGENT"
    )

    # Claude
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    ai_model: str = Field(default="claude-opus-5-5", alias="TH_AI_MODEL")

    # Optional providers / collectors
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")
    youtube_api_key: str = Field(default="", alias="YOUTUBE_API_KEY")
    core_api_key: str = Field(default="", alias="CORE_API_KEY")
    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")
    facebook_access_token: str = Field(default="", alias="FACEBOOK_ACCESS_TOKEN")
    instagram_access_token: str = Field(default="", alias="INSTAGRAM_ACCESS_TOKEN")
    instagram_business_account_id: str = Field(default="", alias="INSTAGRAM_BUSINESS_ACCOUNT_ID")
    x_bearer_token: str = Field(default="", alias="X_BEARER_TOKEN")
    tiktok_client_key: str = Field(default="", alias="TIKTOK_CLIENT_KEY")
    tiktok_client_secret: str = Field(default="", alias="TIKTOK_CLIENT_SECRET")
    telegram_api_id: str = Field(default="", alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(default="", alias="TELEGRAM_API_HASH")

    tesseract_cmd: str = Field(default="", alias="TH_TESSERACT_CMD")

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'tarbiyah.db').as_posix()}"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def text_dir(self) -> Path:
        return self.data_dir / "text"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.files_dir, self.text_dir, self.outputs_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_config() -> Config:
    cfg = Config()
    cfg.data_dir = Path(cfg.data_dir).resolve()
    cfg.ensure_dirs()
    return cfg


def reset_config_cache() -> None:
    get_config.cache_clear()
