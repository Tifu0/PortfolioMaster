"""FastAPI application entrypoint for watchlistTracker (WT).

Modularized from the original monolith into dedicated domain routers:
- config: Healthcheck and runtime configuration
- positions: Positions and aggregated metrics
- instruments: Instruments CRUD and price resolution
- refresh: Batch quotes refresh and SSE streaming
- import_export: File preview/commit and CSV/Excel/JSON exports
- backup: Database wipe and snapshot backup/restore
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

# Silence known upstream Pandas / yfinance deprecation warnings (e.g. Pandas4Warning inplace keyword)
warnings.filterwarnings("ignore", message=".*inplace.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="yfinance")

# Ensure 'src' and root directories are discoverable in sys.path on Render/Linux deployments
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_SRC_DIR = _ROOT_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from portfoliomaster.core.config import get_batch_size, get_refresh_interval
from portfoliomaster.db.connection import init_db
from portfoliomaster.db.repository import get_all_instruments
from portfoliomaster.providers.yahoo_adapter import YahooAdapter

from .routers.backup import router as backup_router
from .routers.config import router as config_router
from .routers.import_export import router as import_export_router
from .routers.instruments import (
    _fetch_historical_quote_and_date,
    _fetch_historical_quote_for_date,
    _fetch_start_of_year_quote,
    router as instruments_router,
)
from .routers.positions import router as positions_router
from .routers.refresh import (
    _execute_refresh_all,
    _state,
    router as refresh_router,
)

from .common import is_multi_tenant_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def background_refresh_loop():
    """Background worker that periodically refreshes market data quotes."""
    await asyncio.sleep(2)
    while True:
        try:
            enable_bg = os.environ.get("ENABLE_BACKGROUND_REFRESH", "true").lower() not in ("false", "0", "no")
            interval = get_refresh_interval()
            if not enable_bg or interval <= 0:
                logger.info("[AutoRefresh] Automatic refresh disabled (ENABLE_BACKGROUND_REFRESH=false or REFRESH_INTERVAL_SECONDS <= 0).")
                await asyncio.sleep(60)
                continue

            logger.info(
                f"[AutoRefresh] Worker running. Interval: {interval:.0f}s | "
                f"Batch size: {get_batch_size()} tickers."
            )
            await asyncio.sleep(interval)

            has_instruments = False
            if is_multi_tenant_db():
                from portfoliomaster.db.session import session_scope
                from portfoliomaster.db.schema import UserInstrument
                from sqlalchemy import func, select
                try:
                    with session_scope() as session:
                        cnt = session.scalar(
                            select(func.count()).select_from(UserInstrument).where(UserInstrument.active.is_(True))
                        )
                        has_instruments = bool(cnt and cnt > 0)
                except Exception as ex:
                    logger.warning("[AutoRefresh] Could not query active instruments: %s", ex)
            else:
                instruments = get_all_instruments()
                has_instruments = bool(instruments)

            if not has_instruments:
                logger.info("[AutoRefresh] No active instruments registered. Skipping scheduled refresh.")
                continue

            logger.info("[AutoRefresh] Starting scheduled refresh...")
            result = await asyncio.to_thread(_execute_refresh_all)
            logger.info(
                f"[AutoRefresh] Refresh finished: {result.get('updated', 0)} updated, "
                f"{result.get('failed', 0)} failed of {result.get('total', 0)} total."
            )
        except asyncio.CancelledError:
            logger.info("[AutoRefresh] Background worker stopping.")
            break
        except Exception as e:
            logger.error(f"[AutoRefresh] Unexpected error during refresh cycle: {e}")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialise database on startup and run background refresh worker."""
    if is_multi_tenant_db():
        from portfoliomaster.db.session import session_scope
        from sqlalchemy import text
        try:
            with session_scope() as session:
                session.execute(text("SELECT 1"))
            logger.info("[Startup] Connected successfully to PostgreSQL database.")
        except Exception as e:
            logger.error("[Startup] Failed to connect to PostgreSQL database: %s", e)
            if os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod") or os.environ.get("RENDER", "").lower() == "true":
                raise
    else:
        try:
            init_db()
        except Exception as e:
            logger.warning("[Startup] Local SQLite init_db skipped or non-fatal: %s", e)

    enable_bg = os.environ.get("ENABLE_BACKGROUND_REFRESH", "true").lower() not in ("false", "0", "no")
    task = None
    if enable_bg and get_refresh_interval() > 0:
        task = asyncio.create_task(background_refresh_loop())
    else:
        logger.info("[Startup] Background refresh loop not started (disabled or REFRESH_INTERVAL_SECONDS <= 0).")

    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="watchlistTracker API",
    description="High-scale, multi-tenant financial watchlist tracking engine (WT)",
    version="2.0.0",
    lifespan=lifespan,
)

cors_origins_str = os.environ.get("CORS_ORIGINS", "")
is_prod = (
    os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod")
    or os.environ.get("RENDER", "").lower() == "true"
)

if cors_origins_str:
    origins = [orig.strip() for orig in cors_origins_str.split(",") if orig.strip()]
    if "*" in origins:
        raise RuntimeError(
            "[Security Error] Wildcard '*' is forbidden in CORS_ORIGINS when allow_credentials=True. "
            "Please configure explicit allowed origins (e.g. 'https://your-frontend.vercel.app')."
        )
elif is_prod:
    raise RuntimeError(
        "[Configuration Error] CORS_ORIGINS must be set in production / Render environment. "
        "Set CORS_ORIGINS to the comma-separated list of allowed frontend origins (e.g. 'https://your-frontend.vercel.app')."
    )
else:
    # Explicit safe development origins
    origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    max_age=86400,
)

# Mount domain routers
app.include_router(config_router)
app.include_router(positions_router)
app.include_router(instruments_router)
app.include_router(refresh_router)
app.include_router(import_export_router)
app.include_router(backup_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Standardize HTTPExceptions under RFC 7807 problem details while preserving 'detail'."""
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": "about:blank",
            "title": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
            "status": exc.status_code,
            "detail": exc.detail,
            "instance": request.url.path,
        },
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Capture unexpected exceptions returning RFC 7807 without leaking internal traces in prod."""
    logger.exception(
        "[GlobalExceptionHandler] Unhandled exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    # Ensure immediate flush to standard error stream for cloud log collection (Render/Docker)
    sys.stderr.write(f"\n[ERROR] Unhandled exception on {request.method} {request.url.path}: {exc}\n")
    sys.stderr.flush()

    is_prod_env = (
        os.environ.get("ENVIRONMENT", "").lower() in ("production", "prod")
        or os.environ.get("RENDER", "").lower() == "true"
    )
    exc_name = type(exc).__name__
    if "IntegrityError" in exc_name or "CheckViolation" in str(exc) or "NotNullViolation" in str(exc):
        detail_message = f"Database constraint violation: {exc}"
    elif is_prod_env:
        detail_message = "An unexpected internal error occurred on the server."
    else:
        detail_message = f"Internal Server Error: {exc_name}: {str(exc)}"

    return JSONResponse(
        status_code=500,
        content={
            "type": "about:blank",
            "title": "Internal Server Error",
            "status": 500,
            "detail": detail_message,
            "instance": request.url.path,
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Handle browser favicon request silently without 404 logs."""
    return Response(status_code=204)

# Re-exports for backward-compatibility with test suites and external consumers
__all__ = [
    "app",
    "YahooAdapter",
    "_execute_refresh_all",
    "_fetch_historical_quote_and_date",
    "_fetch_historical_quote_for_date",
    "_fetch_start_of_year_quote",
    "_state",
]

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("backend.api.main:app", host=host, port=port, reload=False)
