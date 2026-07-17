"""
Unit tests for the HiveBox FastAPI application.

This module verifies that the API endpoints behave as expected.
It tests the `/version` endpoint and the `/temperature` endpoint
using FastAPI's TestClient. The endpoints are tested using mocked
responses to ensure full isolation from infrastructure services.
"""

import pytest
from fastapi.testclient import TestClient

from src.app import app

client = TestClient(app)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# GET /version
# ---------------------------------------------------------------------------


def test_version_endpoint(mocker):
    """
    Tests the /version endpoint.

    The variable `__version__` is mocked to return a fixed version string.
    The test verifies that the endpoint responds with HTTP 200
    and that the returned JSON payload contains the 'version' field.
    """
    mocker.patch("src.app.__version__", "1.0.0")

    response = client.get("/version")

    assert response.status_code == 200
    assert "version" in response.json()


# ---------------------------------------------------------------------------
# GET /temperature
# ---------------------------------------------------------------------------


class TestTemperatureEndpoint:
    """Unit tests for the /temperature endpoint."""

    def test_returns_cached_data_when_cache_is_fresh(self, mocker):
        """
        Returns cached temperature data without hitting the live source when the cache is fresh.

        Mocks the cache as not stale and pre-populated with a valid entry,
        then verifies the endpoint responds with that cached data (source="cache")
        and never calls the live temperature fetch or updates the cache.
        """
        mocker.patch("src.app.is_cache_stale", return_value=False)
        mocker.patch(
            "src.app.get_temperature_cache",
            return_value={"average_temperature": 23.5, "status": "Good"},
        )
        live_mock = mocker.patch("src.app.get_average_temperature")
        set_cache_mock = mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json() == {
            "average_temperature": 23.5,
            "status": "Good",
            "source": "cache",
        }
        live_mock.assert_not_called()
        set_cache_mock.assert_not_called()

    def test_returns_live_data_when_no_cache_entry(self, mocker):
        """
        Fetches and caches live temperature data when the cache is stale.

        Mocks the cache as stale and the live source as returning a valid reading,
        then verifies the endpoint responds with fresh data (source="live")
        and stores the new reading in the cache exactly once.
        """
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.get_average_temperature", return_value=23.5)
        mocker.patch("src.app.get_temperature_status", return_value="Good")
        set_cache_mock = mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json() == {
            "average_temperature": 23.5,
            "status": "Good",
            "source": "live",
        }
        set_cache_mock.assert_called_once_with(23.5, "Good")

    def test_returns_503_when_no_data_available(self, mocker):
        """
        Returns a 503 error when no live or cached temperature data is available.

        Mocks the cache as stale and the live source as returning no data,
        then verifies the endpoint responds with a 503 status and
        an appropriate error message, without computing a status or
        updating the cache.
        """
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.get_average_temperature", return_value=None)
        status_mock = mocker.patch("src.app.get_temperature_status")
        set_cache_mock = mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.status_code == 503
        assert response.json() == {"detail": "No recent temperature data"}
        status_mock.assert_not_called()
        set_cache_mock.assert_not_called()
