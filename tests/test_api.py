"""
Unit tests for the HiveBox FastAPI application.

This module verifies that the API endpoints behave as expected.
It tests the `/version` endpoint and the `/temperature` endpoint
using FastAPI's TestClient.
"""

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_version_endpoint():
    """
    Tests the /version endpoint.

    This test ensures that the endpoint responds successfully
    and that the returned JSON payload contains the 'version' field.
    """
    response = client.get("/version")

    assert response.status_code == 200
    assert "version" in response.json()

def test_temperature_endpoint():
    """
    Tests the /temperature endpoint.

    The endpoint may return:
    - 200 if temperature data is successfully retrieved and averaged.
    - 503 if no valid temperature data is available.

    If the response is successful, the returned JSON must contain
    the 'average_temperature' field.
    """
    response = client.get("/temperature")

    assert response.status_code in [200, 503]

    if response .status_code == 200:
        assert "average_temperature" in response.json()
