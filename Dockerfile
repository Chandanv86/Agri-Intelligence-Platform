# Single image, reused for every service in docker-compose.yml (api, worker,
# beat, flower) -- they differ only by CMD, so one build keeps the images in
# sync instead of drifting across four separate Dockerfiles. See
# docs/PRODUCTION_IMPLEMENTATION_PLAN.md §1 for why these services exist.
FROM python:3.12-slim

WORKDIR /app

# System deps: none required for the base (DEMO-capable) requirements.txt --
# psycopg[binary] and celery[redis] both ship prebuilt wheels for this base
# image. Keep it that way; if requirements-live.txt (geopandas/shapely) is
# ever baked into an image instead of installed at runtime, add
# build-essential/gdal here in a separate build stage rather than bloating
# this one.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status==200 else 1)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
