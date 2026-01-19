import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def get_export_dir() -> Path:
    export_dir = os.getenv("SERVICE_DESCRIPTION_DIR", "Service-description")
    return Path(export_dir).resolve()


def create_app() -> FastAPI:
    app = FastAPI(title="Confluence HTML Export Viewer")
    export_dir = get_export_dir()
    if not export_dir.exists():
        raise RuntimeError(f"Export directory not found: {export_dir}")

    app.mount("/", StaticFiles(directory=export_dir, html=True), name="static")
    return app


app = create_app()
