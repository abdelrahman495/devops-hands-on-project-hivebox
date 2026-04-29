"""
HiveBox API
"""

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from src.sensebox_service import get_average_temperature
from src.temperature_utils import get_temperature_status

# Using the Semantic Versioning v0.6.0
__version__ = "0.6.0"

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


@app.get("/temperature")
def temperature():
    """
    Returns average temperature from nearby senseBoxes
    and a status based on its value.
    """
    avg_temp = get_average_temperature()

    if avg_temp is None:
        raise HTTPException(status_code=503, detail="No recent temperature data")

    status = get_temperature_status(avg_temp)

    return {"average_temperature": avg_temp, "status": status}
