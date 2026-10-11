from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str
    db_password: str = ""
    db_name: str
    mcp_api_key: str = ""
    max_rows: int = 200
    query_timeout_seconds: int = 15
    confirm_ttl_seconds: int = 300
    host: str = "127.0.0.1"
    port: int = 8000
    audit_log: str = "audit.log"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
