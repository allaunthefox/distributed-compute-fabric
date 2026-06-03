"""
Hermes Configuration Management

Uses Pydantic Settings for environment-based configuration.

Author: Mistral Vibe
Version: 1.0.0
Date: 2026-06-01
"""

from functools import lru_cache
from typing import List

from pydantic import Field, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Application
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 4
    DEBUG: bool = True
    SERVE_STATIC: bool = False
    
    # CORS
    CORS_ORIGINS: List[AnyHttpUrl] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://localhost:3000",
        "https://localhost:8080",
        # Production domains (set via HERMES_CORS_ORIGINS env var)
        # Example: HERMES_CORS_ORIGINS='["https://api.researchstack.info","https://hermes.researchstack.info"]'
    ]
    
    # Ray Cluster
    RAY_HEAD_HOST: str = "raycluster-head-svc.ray-system.svc.cluster.local"
    RAY_HEAD_PORT: int = 8265
    RAY_DASHBOARD_USER: str = "admin"
    RAY_DASHBOARD_PASSWORD: str = ""
    
    # Redis (for caching)
    REDIS_HOST: str = "redis-service.ray-system.svc.cluster.local"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60  # seconds
    
    # Authentication
    AUTH_ENABLED: bool = True
    AUTH_TYPE: str = "jwt"  # or "basic", "none"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 30
    
    # Model Configuration
    MODEL_CACHE_DIR: str = "/cache/models"
    MAX_CONCURRENT_REQUESTS: int = 100
    REQUEST_TIMEOUT: int = 300  # seconds
    
    # Monitoring
    PROMETHEUS_ENABLED: bool = True
    METRICS_PORT: int = 9090
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # or "text"
    
    # Database (for request logging)
    DATABASE_URL: str = "sqlite:///./hermes.db"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache()
def get_settings():
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
