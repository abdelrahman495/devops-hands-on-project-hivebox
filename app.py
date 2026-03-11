"""
HiveBox API
"""

from fastapi import FastAPI

# Using the Semantic Versioning v0.1.0
__version__ = "0.1.0"

app = FastAPI()

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
