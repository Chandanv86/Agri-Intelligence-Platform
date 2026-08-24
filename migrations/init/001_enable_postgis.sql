-- Runs once, automatically, the first time the `db` container initializes
-- its data volume (standard postgres image behavior for anything mounted at
-- /docker-entrypoint-initdb.d/). Enables PostGIS ahead of the Alembic
-- migrations described in docs/PRODUCTION_IMPLEMENTATION_PLAN.md §7 --
-- those migrations assume `geometry(...)` columns are already available and
-- shouldn't have to special-case "first ever migration also installs the
-- extension".
CREATE EXTENSION IF NOT EXISTS postgis;
