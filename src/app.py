"""
HiveBox API
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from src.cache_service import (
    get_temperature_cache,
    is_cache_stale,
    set_temperature_cache,
)
from src.sensebox_service import get_average_temperature
from src.storage_service import StorageError, store_temperature_data
from src.temperature_utils import get_temperature_status

# Using the Semantic Versioning v0.9.0
__version__ = "0.9.0"

# How often the background task persists temperature data to MinIO (seconds)
STORE_INTERVAL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_temperature_data():
    """
    Resolves the current temperature reading using a cache-first strategy:

    1. If a fresh Valkey cache entry exists, return it with `source='cache'`.
    2. Otherwise fall back to the live senseBox API, write the result back to
       the cache, and return `source='live'`.
    3. Return `None` when neither source yields data.

    Returns:
        tuple[float, str, str] | None:
            A tuple of (average_temperature, status, source) or `None` if no
            data is available.
    """
    if not is_cache_stale():
        cached = get_temperature_cache()
        if cached:
            return cached["average_temperature"], cached["status"], "cache"

    avg_temp = get_average_temperature()
    if avg_temp is None:
        return None

    status = get_temperature_status(avg_temp)

    set_temperature_cache(avg_temp, status)

    return avg_temp, status, "live"


# ---------------------------------------------------------------------------
# Background scheduler
# ---------------------------------------------------------------------------


async def _periodic_store():
    """
    Background coroutine that persists temperature data to MinIO every
    `STORE_INTERVAL_SECONDS` seconds.

    Data is taken from the Valkey cache when a fresh entry is available so
    that MinIO snapshots reflect exactly what the application is serving to
    clients. The live senseBox API is only called when the cache is stale or
    absent. If no temperature data is available at all, the run is skipped.
    Storage failures (`StorageError`) are caught and printed but never
    propagate so the task keeps running.
    """
    loop = asyncio.get_running_loop()
    next_run = loop.time() + STORE_INTERVAL_SECONDS

    while True:
        await asyncio.sleep(max(0, next_run - loop.time()))
        next_run += STORE_INTERVAL_SECONDS

        result = await asyncio.to_thread(_resolve_temperature_data)

        if result is None:
            print("Scheduled store skipped: no temperature data available")
            continue

        avg_temp, status, source = result

        try:
            object_name = await asyncio.to_thread(
                store_temperature_data, avg_temp, status
            )
            print(f"Scheduled store completed: {object_name} [source={source}]")
        except StorageError as exc:
            print(f"Scheduled store failed: {exc}")


@asynccontextmanager
async def lifespan(app):  # pylint: disable=redefined-outer-name, unused-argument
    """
    Starts/stops the periodic MinIO store task around the app's lifetime.
    """
    task = asyncio.create_task(_periodic_store())
    print(f"Periodic store task started (interval: {STORE_INTERVAL_SECONDS} s)")
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        print("Periodic store task stopped")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


# Create a FastAPI "instance"
app = FastAPI(lifespan=lifespan)

# Instrument the app with default metrics and expose the metrics
Instrumentator().instrument(app).expose(app)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/")
def root():
    """
    Returns a simple greeting.
    """
    return {"message": "Hello World"}


@app.get("/version")
def version():
    """
    Returns the current app version.
    """
    return {"version": __version__}


@app.get("/temperature", responses={503: {"description": "No recent temperature data"}})
def temperature():
    """
    Returns average temperature from nearby senseBoxes,
    a status based on its value, and the data source.
    """
    result = _resolve_temperature_data()

    if result is None:
        raise HTTPException(status_code=503, detail="No recent temperature data")

    avg_temp, status, source = result

    return {"average_temperature": avg_temp, "status": status, "source": source}


@app.get(
    "/store",
    responses={
        503: {"description": "No recent temperature data"},
        500: {"description": "Storage operation failed"},
    },
)
def store():
    """
    Stores temperature data directly in MinIO
    instead of waiting for the next scheduled run.
    """
    result = _resolve_temperature_data()

    if result is None:
        raise HTTPException(status_code=503, detail="No recent temperature data")

    avg_temp, status, source = result

    try:
        object_name = store_temperature_data(avg_temp, status)
    except StorageError as exc:
        print(f"Manual store to MinIO failed: {exc}")
        raise HTTPException(status_code=500, detail="Storage operation failed") from exc

    return {
        "object": object_name,
        "source": source,
    }
