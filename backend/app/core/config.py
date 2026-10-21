from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfiguration aus Umgebungsvariablen; lokal zusätzlich aus der .env im Projektordner."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str
    windiq_api_base_url: str = "https://windiq-mock-api.sliplane.app"
    windiq_client_id: str
    windiq_client_secret: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()
