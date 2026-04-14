"""
Unit tests for the HiveBox FastAPI application.

This module verifies that the API endpoints behave as expected.
It tests the `/version` endpoint and the `/temperature` endpoint
using FastAPI's TestClient. The endpoints are tested using mocked
responses to ensure full isolation
"""

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_version_endpoint(mocker):
    """
    Tests the /version endpoint.

    The variable `__version__` is mocked to return a fixed version string.
    The test verifies that the endpoint responds with HTTP 200
    and that the returned JSON payload contains the 'version' field.
    """
    mocker.patch("app.__version__", "1.0.0")

    response = client.get("/version")

    assert response.status_code == 200
    assert "version" in response.json()


def test_temperature_endpoint_success(mocker):
    """
    Tests the /temperature endpoint when temperature data is available.

    The functions `get_average_temperature` and `get_temperature_status`
    are mocked to return a valid response. The test verifies that the
    endpoint responds with HTTP 200 and that the returned JSON payload
    contains the correct 'average_temperature' and 'status' values.
    """

    mocker.patch("app.get_average_temperature", return_value=23.5)
    mocker.patch("app.get_temperature_status", return_value="Good")

    response = client.get("/temperature")

    assert response.status_code == 200
    assert response.json() == {"average_temperature": 23.5, "status": "Good"}


def test_temperature_endpoint_no_data(mocker):
    """
    Tests the /temperature endpoint when no temperature data is available.

    The function `get_average_temperature` is mocked to return None,
    simulating a situation where no valid temperature readings exist.
    The test verifies that the endpoint responds with HTTP 503 to
    indicate that the service cannot provide temperature data.
    """

    mocker.patch("app.get_average_temperature", return_value=None)

    response = client.get("/temperature")

    assert response.status_code == 503
