"""Celery tasks -- see docs/PRODUCTION_IMPLEMENTATION_PLAN.md §2-3.

The queue-backed LIVE path. `build_snapshot_task` routes through
`SnapshotOrchestrator`, which sends fixture districts (Ludhiana/Patna) to the
DEMO `SnapshotService` (unchanged) and every other registered, live-capable
district to `LiveSnapshotBuilder` (real SentinelHub/GEE/AMED/WorldCereal
calls, each individually isolated). A registered district with NO live
credentials raises `NoFixtureAvailable`, which surfaces as the same 501 the
synchronous endpoint returns -- so behavior stays consistent whichever path a
caller takes.

Note: by default the API builds live snapshots synchronously and never
enqueues here (see `settings.live_snapshot_sync` in app/core/config.py). This
task is exercised only when LIVE_SNAPSHOT_SYNC=false, i.e. the 202/poll path.
"""

from celery.utils.log import get_task_logger

from .celery_app import celery_app
from ..services.snapshot import SnapshotOrchestrator, NoFixtureAvailable
from ..services.geography import GeographyService

logger = get_task_logger(__name__)

_geo = GeographyService()
_orchestrator = SnapshotOrchestrator(_geo)


@celery_app.task(
    name="agri.build_snapshot",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def build_snapshot_task(self, admin_id: str, crop_id: str, season_id: str) -> dict:
    """Builds an AgriSnapshot off the request path via SnapshotOrchestrator
    (fixture districts → DEMO service; live-capable districts →
    LiveSnapshotBuilder). Returns the raw JSON-serializable AgriSnapshot dict;
    `GET /tasks/{task_id}` in routes.py hands it back under the "snapshot" key.
    """
    logger.info("build_snapshot_task start admin_id=%s crop_id=%s season_id=%s", admin_id, crop_id, season_id)
    try:
        snap = _orchestrator.get_snapshot(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
    except NoFixtureAvailable as e:
        # Registered district with no live credentials configured -- mirrors the
        # synchronous endpoint's 501 semantics (see routes.py resolve_source()).
        logger.warning("build_snapshot_task no_fixture admin_id=%s: %s", admin_id, e)
        raise
    return snap.model_dump(mode="json")


@celery_app.task(name="agri.build_baseline")
def build_baseline_task(country_id: str) -> None:
    """Placeholder for the monthly historical-baseline batch job described in
    docs/PRODUCTION_IMPLEMENTATION_PLAN.md §4. Not implemented yet -- needs
    the Postgres `historical_baseline` table (plan §7) and live GEE
    credentials (plan §3.1) before it can do real work.
    """
    logger.info("build_baseline_task requested for country_id=%s (not yet implemented, see plan §4)", country_id)
    raise NotImplementedError(
        "Historical baseline pipeline is planned but not implemented -- "
        "see docs/PRODUCTION_IMPLEMENTATION_PLAN.md §4."
    )
