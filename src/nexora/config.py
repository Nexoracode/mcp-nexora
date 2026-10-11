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
    confirm_ttl_seconds: int = 120
    confirm_secret: str = ""  # HMAC key for confirm tokens; falls back to mcp_api_key
    db_ssl: bool = False  # verified TLS to the database
    db_pool_max: int = 2
    # Raw SQL writes (preview_write / execute_write) are off by default; changes go through the Nexora API.
    enable_sql_write: bool = False
    nexora_api_url: str = ""  # e.g. https://panel.example.com
    nexora_api_token: str = ""  # must equal OWNER_API_TOKEN in the Nexora panel
    host: str = "127.0.0.1"
    port: int = 8000
    audit_log: str = "audit.log"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
