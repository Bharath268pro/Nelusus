"""Configuration management for the Security Proxy"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    environment: str = "development"
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"

    # JWT/Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # Auth0/Okta
    auth0_domain: str
    auth0_client_id: str
    auth0_client_secret: str
    auth0_api_identifier: str

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_cache_ttl: int = 3600

    # Database
    database_url: str

    # Salesforce
    salesforce_client_id: str
    salesforce_client_secret: str
    salesforce_instance_url: str

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
