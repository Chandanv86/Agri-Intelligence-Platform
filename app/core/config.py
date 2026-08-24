from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel
import os

from dotenv import load_dotenv

# Load a repo-root .env for LOCAL (non-Docker) runs such as
# `uvicorn app.main:app` or `python scripts/try_live_snapshot.py`.
#
# Why this is required: Settings below reads os.getenv() at IMPORT time (the
# defaults are evaluated when the class body runs). Without this call nothing
# ever populates the environment locally, so every credential comes back None
# and is_live_capable() returns False -- which is exactly why registered
# districts were returning a 501 despite a correctly filled-in .env.
#
# In Docker this is a safe no-op: docker-compose already injects these via
# `env_file: .env`, and load_dotenv() does NOT override variables that are
# already present in the environment (override defaults to False).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "development")
    default_data_status: str = os.getenv("DEFAULT_DATA_STATUS", "DEMO")

    sentinelhub_base_url: str = os.getenv("SENTINELHUB_BASE_URL", "https://sh.dataspace.copernicus.eu")
    sentinelhub_client_id: str | None = os.getenv("SENTINELHUB_CLIENT_ID") or None
    sentinelhub_client_secret: str | None = os.getenv("SENTINELHUB_CLIENT_SECRET") or None
    # Optional override. Left unset, the client derives the correct endpoint
    # from the base URL (CDSE uses a separate Keycloak identity host).
    sentinelhub_token_url: str | None = os.getenv("SENTINELHUB_TOKEN_URL") or None

    cdse_stac_endpoint: str = os.getenv("CDSE_STAC_ENDPOINT", "https://stac.dataspace.copernicus.eu/v1/")

    gee_project: str | None = os.getenv("GEE_PROJECT") or None
    gee_service_account_json_path: str | None = os.getenv("GEE_SERVICE_ACCOUNT_JSON_PATH") or None

    amed_api_key: str | None = os.getenv("AMED_API_KEY") or None
    amed_enabled: bool = os.getenv("AMED_ENABLED", "false").lower() == "true"

    # --- Async task queue (see docs/PRODUCTION_IMPLEMENTATION_PLAN.md §2) ---
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

    # --- Tier 1/2 datastore (see docs/PRODUCTION_IMPLEMENTATION_PLAN.md §7) ---
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://agri:agri@db:5432/agri_intel"
    )

    # --- Live snapshot execution mode (see docs/PRODUCTION_IMPLEMENTATION_PLAN.md §2) ---
    # When true (the default), the LIVE branch of
    # GET /agri/areas/{admin_id}/snapshot builds the snapshot synchronously
    # in-process and returns 200 with the full {snapshot, renderable_cards}
    # payload -- no Redis, no Celery worker, no frontend polling required, so a
    # single click shows real connector data immediately.
    #
    # Set LIVE_SNAPSHOT_SYNC=false to use the queue-backed path instead: the
    # endpoint returns 202 + task_id, a Celery worker builds it, and the
    # frontend polls /tasks/{task_id} (needs Redis + a running worker).
    live_snapshot_sync: bool = os.getenv("LIVE_SNAPSHOT_SYNC", "true").lower() == "true"

    def is_live_capable(self) -> bool:
        """LIVE mode requires at least one real evidence connector to be configured.
        This is a hard product rule (see docs/KNOWN_LIMITATIONS.md): the app must
        NEVER silently substitute demo values into LIVE mode."""
        return bool(self.sentinelhub_client_id and self.sentinelhub_client_secret) or bool(self.gee_project)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
