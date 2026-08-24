from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from ..services.geography import GeographyService, UnknownAdminUnit
from ..services.geography_match import GeographyMatchService, GEOMETRY_LEVEL_NOTE
from ..services.catalog import CatalogService
from ..services.card_manifest import CardManifestService
from ..services.snapshot import (
    SnapshotOrchestrator, SnapshotSource, NoFixtureAvailable, GeometryNotAvailable,
)
from ..services.country_adapters.registry import get_adapter, all_country_ids
from ..core.config import settings

router = APIRouter(prefix="/api/v1")

_geo = GeographyService()
_catalog = CatalogService()
_cards = CardManifestService()
_orchestrator = SnapshotOrchestrator(_geo)
_matcher = GeographyMatchService(_geo)


class MatchRequest(BaseModel):
    country_id: str
    names: list[str]


@router.get("/geography/countries")
def list_countries():
    return _geo.countries()


@router.get("/geography/{country_id}/schema")
def country_schema(country_id: str):
    try:
        schema = _geo.schema_for(country_id)
    except KeyError:
        raise HTTPException(404, f"Unknown country_id {country_id}")
    adapter = get_adapter(country_id)
    return {**schema, "level_names_from_adapter": adapter.hierarchy_level_names()}


@router.get("/geography/{country_id}/admin1")
def list_admin1(country_id: str):
    return _geo.admin1_for_country(country_id)


@router.get("/geography/{country_id}/crosswalk")
def crosswalk(country_id: str):
    return _geo.crosswalk_groups(country_id)


@router.get("/geography/resolve/{admin_id}")
def resolve(admin_id: str):
    try:
        return _geo.resolve(admin_id)
    except UnknownAdminUnit:
        raise HTTPException(404, f"Unknown admin_id {admin_id}")


@router.get("/geography/{admin_id}/children")
def children(admin_id: str):
    return _geo.children(admin_id)


@router.get("/crops")
def crops():
    return _catalog.crops()


@router.get("/seasons")
def seasons(country_id: str, crop_id: str | None = None):
    return _catalog.seasons_for(country_id, crop_id)


@router.get("/cards/manifest")
def card_manifest(tier: int | None = None, theme: str | None = None):
    if tier is not None:
        return _cards.by_tier(tier)
    if theme is not None:
        return _cards.by_theme(theme)
    return _cards.all_cards()


@router.get("/agri/areas/{admin_id}/snapshot")
def snapshot(admin_id: str, crop_id: str, season_id: str, response: Response):
    """The one endpoint every card renders from. See docs/ARCHITECTURE.md §3.

    Routing is owned by SnapshotOrchestrator so this endpoint and the Celery
    worker can never drift apart: fixture districts (Ludhiana/Patna) return the
    DEMO snapshot, every other registered district goes to the real connector
    fan-out. With LIVE_SNAPSHOT_SYNC=true (the default) that live build runs
    in-process and returns 200 with the same {snapshot, renderable_cards}
    shape the frontend already destructures -- no Redis, no Celery, no polling.
    Set it false to get 202 + a /tasks/{task_id} poll instead.
    """
    try:
        source = _orchestrator.resolve_source(admin_id)
    except UnknownAdminUnit:
        raise HTTPException(404, f"Unknown admin_id {admin_id}")
    except NoFixtureAvailable as e:
        raise HTTPException(501, str(e))

    if source is SnapshotSource.LIVE and not settings.live_snapshot_sync:
        # Queue-backed live path -- needs Redis + a running worker.
        from ..workers.tasks import build_snapshot_task

        task = build_snapshot_task.delay(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
        response.status_code = 202
        response.headers["Location"] = f"/api/v1/tasks/{task.id}"
        return {"task_id": task.id, "status_url": f"/api/v1/tasks/{task.id}", "mode": "async"}

    try:
        snap = _orchestrator.get_snapshot(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
    except UnknownAdminUnit:
        raise HTTPException(404, f"Unknown admin_id {admin_id}")
    except NoFixtureAvailable as e:
        raise HTTPException(501, str(e))
    except GeometryNotAvailable as e:
        raise HTTPException(422, f"No usable boundary geometry for {admin_id}: {e}")

    payload = snap.model_dump(mode="json")
    renderable = _cards.renderable_cards(payload)
    return {"snapshot": payload, "renderable_cards": renderable}


@router.post("/agri/areas/{admin_id}/snapshot/async", status_code=202)
def enqueue_snapshot(admin_id: str, crop_id: str, season_id: str, response: Response):
    """Async companion to GET /agri/areas/{admin_id}/snapshot.

    Explicitly enqueues the queue-backed path regardless of the
    LIVE_SNAPSHOT_SYNC setting. The worker routes through the same
    SnapshotOrchestrator the synchronous endpoint uses, so a fixture district
    still comes back DEMO and a live-capable district does the real
    SentinelHub/GEE fan-out. Requires Redis + a running Celery worker; poll
    GET /api/v1/tasks/{task_id} for the result.
    """
    # Imported lazily so `uvicorn app.main:app` and the test suite never need
    # a Celery/Redis connection just to import routes.py.
    from ..workers.tasks import build_snapshot_task

    task = build_snapshot_task.delay(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
    response.headers["Location"] = f"/api/v1/tasks/{task.id}"
    return {"task_id": task.id, "status_url": f"/api/v1/tasks/{task.id}"}


@router.get("/tasks/{task_id}")
def task_status(task_id: str):
    """Polled by the frontend after a 202 from the /snapshot/async endpoint.
    See docs/PRODUCTION_IMPLEMENTATION_PLAN.md §2.2 for the state contract.
    """
    from ..workers.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    if result.state in ("PENDING", "STARTED", "RETRY"):
        return {"state": result.state}
    if result.state == "SUCCESS":
        return {"state": "SUCCESS", "snapshot": result.result}
    if result.state == "FAILURE":
        return {"state": "FAILURE", "error": str(result.result)}
    return {"state": result.state}


@router.post("/geography/match")
def match_names(body: MatchRequest):
    """Batch-resolves real boundary-geometry feature names to this project's
    admin_ids, for tagging map polygons on layer load (see
    services/geography_match.py)."""
    result = _matcher.match_many(body.country_id, body.names)
    return {
        "matches": result,
        "geometry_level_note": GEOMETRY_LEVEL_NOTE.get(body.country_id),
    }


@router.get("/geography/{country_id}/legacy-groups")
def legacy_groups(country_id: str):
    """Used by the map UI when a country's only free boundary geometry is
    coarser than its real analytical level (currently: Kenya provinces vs
    counties) -- lets the frontend offer the finer units as a list."""
    return _geo.crosswalk_groups(country_id)


@router.get("/countries/adapters")
def adapters_summary():
    out = []
    for cid in all_country_ids():
        a = get_adapter(cid)
        out.append({
            "country_id": cid,
            "hierarchy": a.hierarchy_level_names(),
            "crop_mask_primary_source": a.crop_mask_primary_source(),
            "crop_mask_fallback_source": a.crop_mask_fallback_source(),
            "price_currency": a.price_currency(),
            "price_granularity_note": a.price_granularity_note(),
            "rainfall_source": a.rainfall_source(),
            "supports_field_level_crop_source": a.supports_field_level_crop_source(),
        })
    return out
