from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    marsnav_env: str = "development"
    database_url: str = "postgresql+psycopg://marsnav:marsnav@localhost:5432/marsnav"
    data_root: Path = Path("../data")
    cors_origins: str = "http://localhost:5173"
    analyzer_max_area_km2: float = 2500.0          # analysis area limit (50 km x 50 km)
    analyzer_max_download_bytes: int = 64 * 1024 * 1024
    gemma_api_key: str = ""                       # empty: the assistant stays rule-based (set both to enable the model)
    gemma_model: str = ""
    gemma_api_base: str = "https://generativelanguage.googleapis.com/v1beta"

settings = Settings()
