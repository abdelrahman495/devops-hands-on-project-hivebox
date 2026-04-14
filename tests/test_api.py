"""
Unit tests for the HiveBox FastAPI application.

This module verifies that the API endpoints behave as expected.
It tests the `/version` endpoint and the `/temperature` endpoint
using FastAPI's TestClient. The endpoints are tested using mocked
responses to ensure full isolation
"""

from unittest.mock import patch
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


@patch("app.__version__", "1.0.0")
def test_version_endpoint():
    """
    Tests the /version endpoint.

    The variable `__version__` is mocked to return a fixed version string.
    The test verifies that the endpoint responds with HTTP 200
    and that the returned JSON payload contains the 'version' field.
    """
    response = client.get("/version")

    assert response.status_code == 200
    assert "version" in response.json()


@patch("app.get_temperature_status")
@patch("app.get_average_temperature")
def test_temperature_endpoint_success(mock_temp, mock_status):
    """
    Tests the /temperature endpoint when temperature data is available.

    The functions `get_average_temperature` and `get_temperature_status`
    are mocked to return a valid response. The test verifies that the
    endpoint responds with HTTP 200 and that the returned JSON payload
    contains the correct 'average_temperature' and 'status' values.
    """

    mock_temp.return_value = 23.5
    mock_status.return_value = "Good"

    response = client.get("/temperature")

    assert response.status_code == 200
    assert response.json() == {"average_temperature": 23.5, "status": "Good"}


@patch("app.get_average_temperature")
def test_temperature_endpoint_no_data(mock_temp):
    """
    Tests the /temperature endpoint when no temperature data is available.

    The function `get_average_temperature` is mocked to return None,
    simulating a situation where no valid temperature readings exist.
    The test verifies that the endpoint responds with HTTP 503 to
    indicate that the service cannot provide temperature data.
    """

    mock_temp.return_value = None

    response = client.get("/temperature")

    assert response.status_code == 503
