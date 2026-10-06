"""FastAPI application: REST API for the disease surveillance platform."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import get_settings
from .routers import alerts, cases, geo, meta, risk

DESCRIPTION = """
REST API over the surveillance database.

* **cases** - weekly case counts from WHO, Our World in Data and OpenDengue
* **risk** - XGBoost probability of an outbreak over the next four weeks
* **stream** - anomaly alerts raised in real time by the Apache Flink job
"""


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Global Disease Surveillance & Outbreak Analytics API",
        version="1.0.0",
        description=DESCRIPTION,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET"], allow_headers=["*"])
    for module in (meta, geo, cases, risk, alerts):
        app.include_router(module.router, prefix=settings.api_prefix)
    return app


app = create_app()
