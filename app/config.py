"""Engine configuration, loaded from environment / .env (see .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # HTTP server
    engine_host: str = "0.0.0.0"
    engine_port: int = 8000
    schema_version: str = "1.1"

    # Auth (shared with the LMS). Dev defaults make local G3 testing work with no .env.
    engine_api_token: str = "dev-token"
    engine_hmac_secret: str = "dev-secret"

    # Outbound webhooks: default callback if a job omits one, and target for the idle event.
    orchestrator_webhook_url: str = ""

    # AWS / delivery (unused until Phase 6; blank is fine for Phase 3).
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_default_bucket: str = ""
    cloudfront_base_url: str = ""
    asset_base_prefix: str = ""

    # GPU budget + lifecycle
    gpu_budget_seconds: int = 108_000
    idle_shutdown_minutes: int = 0

    # Per-job checkpoint working dir (NOT a queue; the LMS owns the queue)
    work_dir: str = "./work"

    # Stub generator timing (Phase 3 only; real generators arrive in Phase 4/5)
    stub_scene_seconds: float = 0.2


@lru_cache
def get_settings() -> Settings:
    return Settings()
