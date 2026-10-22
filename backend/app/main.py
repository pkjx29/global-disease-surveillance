"""FastAPI application: REST API for the disease surveillance platform."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import get_settings
from .routers import alerts, cases, geo, meta, risk
from .security import require_api_key

DESCRIPTION = """
REST API over the surveillance database.

* **cases** - weekly case counts from WHO, Our World in Data and OpenDengue
* **risk** - XGBoost probability of an outbreak over the next four weeks
* **stream** - anomaly alerts raised in real time by the Apache Flink job

Every route except `/health` and `/ready` needs an `X-API-Key` header (use **Authorize** above)
and is rate-limited per key.
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
    app.include_router(meta.probes, prefix=settings.api_prefix)          # /health and /ready stay open
    for module in (meta, geo, cases, risk, alerts):
        app.include_router(module.router, prefix=settings.api_prefix, dependencies=[Depends(require_api_key)])
    return app


app = create_app()
