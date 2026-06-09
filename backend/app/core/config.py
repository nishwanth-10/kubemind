"""
KubeMind — Core Configuration (Production Edition)
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional, List


def _find_env_file() -> str:
    """Look for .env in CWD, then parent dir, then grandparent dir."""
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.getcwd(), "..", ".env"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"),
    ]
    for path in candidates:
        normalized = os.path.normpath(os.path.abspath(path))
        if os.path.isfile(normalized):
            return normalized
    return ".env"


class Settings(BaseSettings):
    APP_NAME: str = "KubeMind AI"
    APP_VERSION: str = "3.0.0"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: List[str] = ["*"]

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://kubemind:kubemind@localhost:5432/kubemind"
    DB_ENABLED: bool = False
    DB_SSL: str = "require"
    TIMESCALE_ENABLED: bool = False

    # ── JWT Auth ──────────────────────────────────────────────────────────────
    JWT_SECRET: str = "kubemind-change-me-in-production-32chars!"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 24

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = False
    UPSTASH_REDIS_REST_URL: str = ""
    UPSTASH_REDIS_REST_TOKEN: str = ""

    # ── Kubernetes ────────────────────────────────────────────────────────────
    K8S_IN_CLUSTER: bool = False
    K8S_SIMULATION_MODE: bool = False
    K8S_NAMESPACE_FILTER: str = ""

    # ── Prometheus ────────────────────────────────────────────────────────────
    PROMETHEUS_URL: str = "http://localhost:9090"

    # ── Microservices ─────────────────────────────────────────────────────────
    ML_SERVICE_URL: str = "http://localhost:8001"
    AI_SERVICE_URL: str = "http://localhost:8002"

    # ── Ollama AI ─────────────────────────────────────────────────────────────
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"
    OLLAMA_ENABLED: bool = True
    OLLAMA_FALLBACK_MODE: bool = True

    # ── ML ────────────────────────────────────────────────────────────────────
    ML_ANOMALY_THRESHOLD: float = 0.6
    ML_PREDICTION_HORIZON_MINUTES: int = 30

    # ── WebSocket ─────────────────────────────────────────────────────────────
    WS_METRICS_BROADCAST_INTERVAL: int = 3

    # ── Collection ────────────────────────────────────────────────────────────
    METRICS_COLLECTION_INTERVAL: int = 3

    # ── Alerting ──────────────────────────────────────────────────────────────
    ALERT_SLACK_WEBHOOK: str = ""
    ALERT_DISCORD_WEBHOOK: str = ""
    ALERT_EMAIL_SMTP_HOST: str = ""
    ALERT_EMAIL_SMTP_PORT: int = 587
    ALERT_EMAIL_FROM: str = ""
    ALERT_EMAIL_PASSWORD: str = ""
    ALERT_EMAIL_TO: str = ""
    ALERT_WEBHOOK_URL: str = ""
    ALERT_COOLDOWN_SECONDS: int = 300  # 5 min dedup window

    class Config:
        env_file = _find_env_file()
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
