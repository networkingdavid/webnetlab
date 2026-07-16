from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://webnetlab:webnetlab@db:5432/webnetlab"
    REDIS_URL: str = "redis://redis:6379/0"
    SECRET_KEY: str = "change-me-in-production"
    DEFAULT_SNMP_COMMUNITY: str = "public"
    DOCKER_SOCKET: str = "unix:///var/run/docker.sock"
    # Injected by docker-compose from the HOST environment variable HOST_PLATFORM.
    # Values: "Linux" | "Darwin" | "" (empty = auto-detect via platform.system())
    HOST_PLATFORM: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
