# migrations/

`init/001_enable_postgis.sql` runs automatically on first `db` container
start (see `docker-compose.yml`) so PostGIS is available before any real
schema exists.

The actual Alembic migration chain for the `admin_units` / `boundaries` /
`snapshot_cache` / `historical_baseline` / `target_area` / `price_series`
tables (schema in `docs/PRODUCTION_IMPLEMENTATION_PLAN.md` §7.1) is Phase 2
work, gated on the `GeographyService` DB-backed rewrite described in §7.3 of
that plan. `alembic` is already in `requirements.txt`; running
`alembic init migrations` here (once the SQLAlchemy models exist under
`app/models/`) is the next concrete step -- deliberately not scaffolded
speculatively in this pass, since an empty/half-wired Alembic setup is worse
than none.
