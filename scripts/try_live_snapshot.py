#!/usr/bin/env python3
"""Synchronous live-snapshot smoke test -- verify the real connectors WITHOUT
Redis, Celery, or the browser.

This is the fastest way to answer "is my .env actually wired up and are the
live connectors firing?" -- it runs the exact same SnapshotOrchestrator ->
LiveSnapshotBuilder path the API uses, but prints the result to your terminal.

Usage (from the repo root):

    # 1. (optional) install the GEE client for the Earth Engine connectors:
    pip install -r requirements-live.txt

    # 2. make sure .env has SentinelHub creds and/or GEE_PROJECT +
    #    GEE_SERVICE_ACCOUNT_JSON_PATH (config.py's load_dotenv reads it)

    # 3. run it (defaults to Vidisha / rice / kharif):
    python scripts/try_live_snapshot.py
    python scripts/try_live_snapshot.py IND-ADMIN2-MADHYA-PRADESH-VIDISHA rice IND-2026-kharif-rice

What the output tells you:
  - is_live_capable() False        -> the orchestrator raises NoFixtureAvailable
                                       (this is the HTTP 501 you were seeing);
                                       fill your .env credentials.
  - data_status = OBSERVED         -> at least one connector fired (real data!).
  - data_status = UNAVAILABLE      -> live-capable, but every connector failed
                                       (missing earthengine-api, bad creds, or a
                                       geometry gap) -- read the FIRED column and
                                       the warnings your app logs printed.
"""

import json
import os
import sys

# Make `import app...` work when this is run as
# `python scripts/try_live_snapshot.py` from the repo root: Python puts the
# script's own dir (scripts/) on sys.path, not the repo root, so add it here.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing settings triggers config.py's load_dotenv(), so .env is read here.
from app.core.config import settings  # noqa: E402
from app.services.geography import GeographyService  # noqa: E402
from app.services.snapshot import SnapshotOrchestrator, NoFixtureAvailable  # noqa: E402


def main() -> int:
    admin_id = sys.argv[1] if len(sys.argv) > 1 else "IND-ADMIN2-MADHYA-PRADESH-VIDISHA"
    crop_id = sys.argv[2] if len(sys.argv) > 2 else "rice"
    season_id = sys.argv[3] if len(sys.argv) > 3 else "IND-2026-kharif-rice"

    print("=" * 72)
    print(f"admin_id : {admin_id}")
    print(f"crop_id  : {crop_id}")
    print(f"season_id: {season_id}")
    print("-" * 72)
    print(f"is_live_capable         : {settings.is_live_capable()}")
    print(f"  SENTINELHUB_CLIENT_ID : {'set' if settings.sentinelhub_client_id else 'MISSING'}")
    print(f"  SENTINELHUB_SECRET    : {'set' if settings.sentinelhub_client_secret else 'MISSING'}")
    print(f"  GEE_PROJECT           : {settings.gee_project or 'MISSING'}")
    print(f"  GEE_SA_JSON_PATH      : {settings.gee_service_account_json_path or 'MISSING'}")
    if settings.gee_service_account_json_path:
        print(f"  GEE_SA_JSON exists    : {os.path.exists(settings.gee_service_account_json_path)}")
    try:
        import ee  # noqa: F401
        print("  earthengine-api       : installed")
    except Exception:
        print("  earthengine-api       : NOT installed (GEE connectors will not fire)")
    print("=" * 72)

    orch = SnapshotOrchestrator(GeographyService())
    try:
        snap = orch.get_snapshot(admin_id=admin_id, crop_id=crop_id, season_id=season_id)
    except NoFixtureAvailable as exc:
        print(f"\nNoFixtureAvailable (this is the HTTP 501): {exc}\n")
        return 2

    payload = snap.model_dump(mode="json")

    # Summarize which connectors fired (from the sowing lineage sources).
    srcs = (payload.get("sowing") or {}).get("lineage", {}).get("sources", [])
    print("\nCONNECTORS")
    print("-" * 72)
    for s in srcs:
        flag = "FIRED" if s.get("fired") else "  -  "
        print(f"  [{flag}]  {str(s.get('source_id')):16s} via {s.get('access_method')}")
    fired = sum(1 for s in srcs if s.get("fired"))
    print("-" * 72)
    print(f"connectors fired    : {fired}/{len(srcs)}")
    print(f"snapshot.data_status: {payload.get('data_status')}")
    print("=" * 72)

    print("\nFULL SNAPSHOT JSON")
    print("-" * 72)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
