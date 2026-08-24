from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from .api.routes import router as api_router

app = FastAPI(
    title="Agricultural Intelligence Platform",
    description="Hierarchy-aware Sowing Progress + Yield Gap intelligence across India, Kenya, Uganda, Tanzania, Ethiopia, South Africa.",
    version="0.2.0",
)

app.include_router(api_router)

_static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

_templates_dir = Path(__file__).resolve().parent / "templates"


@app.get("/", response_class=HTMLResponse)
def index():
    return (_templates_dir / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}
