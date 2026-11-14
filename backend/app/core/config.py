from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    marsnav_env: str = "development"
    database_url: str = "postgresql+psycopg://marsnav:marsnav@localhost:5432/marsnav"
    data_root: Path = Path("../data")
    cors_origins: str = "http://localhost:5173"

settings = Settings()
