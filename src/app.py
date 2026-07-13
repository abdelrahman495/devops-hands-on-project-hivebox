"""
HiveBox API
"""

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from src.cache_service import (
    get_temperature_cache,
    is_cache_stale,
    set_temperature_cache,
)
from src.sensebox_service import get_average_temperature
from src.temperature_utils import get_temperature_status

# Using the Semantic Versioning v0.7.0
__version__ = "0.7.0"

# Create a FastAPI "instance"
app = FastAPI()

# Instrument the app with default metrics and expose the metrics
Instrumentator().instrument(app).expose(app)


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

    The response is served from the Valkey cache when a fresh entry (<=5 min old)
    is available, avoiding an unnecessary round-trip to the senseBox API.
    On a cache miss or stale entry the live API is queried and the result is
    written back to the cache.
    """
    # --- 1. Try Valkey cache first -----------------------------------------
    if not is_cache_stale():
        cached = get_temperature_cache()
        if cached:
            return {
                "average_temperature": cached["average_temperature"],
                "status": cached["status"],
                "source": "cache",
            }

    # --- 2. Fall back to the live senseBox API -----------------------------
    avg_temp = get_average_temperature()
    if avg_temp is None:
        raise HTTPException(status_code=503, detail="No recent temperature data")

    status = get_temperature_status(avg_temp)

    # Write the fresh value back to the cache
    set_temperature_cache(avg_temp, status)

    return {"average_temperature": avg_temp, "status": status, "source": "live"}
