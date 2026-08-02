"""
Unit tests for the HiveBox FastAPI application.

This module verifies that the API endpoints, the cache-first temperature
resolver, and the periodic storage background task all behave as expected.
Endpoint tests use FastAPI's TestClient; the async background task and lifespan
tests run directly against the coroutines. All calls to infrastructure
services are mocked to ensure full isolation.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.app import (
    STORE_INTERVAL_SECONDS,
    _periodic_store,
    _resolve_temperature_data,
    app,
    lifespan,
)
from src.storage_service import StorageError

client = TestClient(app)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_sleep_for_single_iteration(mocker):
    """
    Patches asyncio.sleep so _periodic_store's `while True` loop runs
    exactly one iteration: the first call returns normally (letting that
    iteration's work happen), and the second call raises CancelledError,
    which mimics real task cancellation and stops the loop deterministically.
    """
    return mocker.patch("asyncio.sleep", side_effect=[None, asyncio.CancelledError()])


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
# _resolve_temperature_data
# ---------------------------------------------------------------------------


class TestResolveTemperatureData:
    """Tests for the _resolve_temperature_data() cache-first helper."""

    def test_returns_cached_data_when_cache_is_fresh(self, mocker):
        """
        When the cache is fresh, the cached reading must be returned
        with source="cache", and the live source must never be queried.
        """
        mocker.patch("src.app.is_cache_stale", return_value=False)
        mocker.patch(
            "src.app.get_temperature_cache",
            return_value={"average_temperature": 23.5, "status": "Good"},
        )
        live_mock = mocker.patch("src.app.get_average_temperature")
        set_cache_mock = mocker.patch("src.app.set_temperature_cache")

        result = _resolve_temperature_data()

        assert result == (23.5, "Good", "cache")
        live_mock.assert_not_called()
        set_cache_mock.assert_not_called()

    def test_falls_back_to_live_when_no_cache_entry(self, mocker):
        """
        When the cache is stale (cache miss or error), the live source must be queried,
        the result written back to the cache, and returned with source="live".
        """
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.get_average_temperature", return_value=23.5)
        mocker.patch("src.app.get_temperature_status", return_value="Good")
        set_cache_mock = mocker.patch("src.app.set_temperature_cache")

        result = _resolve_temperature_data()

        assert result == (23.5, "Good", "live")
        set_cache_mock.assert_called_once_with(23.5, "Good")

    def test_returns_none_when_no_data_available(self, mocker):
        """
        When neither the cache nor the live source has data, the function
        must return None without computing a status or writing to cache.
        """
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.get_average_temperature", return_value=None)
        status_mock = mocker.patch("src.app.get_temperature_status")
        set_cache_mock = mocker.patch("src.app.set_temperature_cache")

        result = _resolve_temperature_data()

        assert result is None
        status_mock.assert_not_called()
        set_cache_mock.assert_not_called()


# ---------------------------------------------------------------------------
# _periodic_store (background task)
# ---------------------------------------------------------------------------


class TestPeriodicStore:
    """Tests for the _periodic_store() background coroutine."""

    @pytest.mark.asyncio
    async def test_stores_data_on_success(self, mocker):
        """
        When a temperature reading is available, the task must resolve it,
        persist it via store_temperature_data, and print a success message
        naming the stored object and its data source.
        """
        _patch_sleep_for_single_iteration(mocker)
        mocker.patch(
            "src.app._resolve_temperature_data",
            return_value=(23.5, "Good", "cache"),
        )
        store_mock = mocker.patch(
            "src.app.store_temperature_data",
            return_value="temperatures/2026/06/01/T12:34:56.789123Z.json",
        )
        print_mock = mocker.patch("builtins.print")

        with pytest.raises(asyncio.CancelledError):
            await _periodic_store()

        store_mock.assert_called_once_with(23.5, "Good")
        print_mock.assert_any_call(
            "Scheduled store completed: "
            "temperatures/2026/06/01/T12:34:56.789123Z.json [source=cache]"
        )

    @pytest.mark.asyncio
    async def test_skips_store_when_no_temperature_data(self, mocker):
        """
        When no temperature data is available at all, the task must skip
        the run, print a message, and never attempt to persist anything.
        """
        _patch_sleep_for_single_iteration(mocker)
        mocker.patch("src.app._resolve_temperature_data", return_value=None)
        store_mock = mocker.patch("src.app.store_temperature_data")
        print_mock = mocker.patch("builtins.print")

        with pytest.raises(asyncio.CancelledError):
            await _periodic_store()

        store_mock.assert_not_called()
        print_mock.assert_any_call(
            "Scheduled store skipped: no temperature data available"
        )

    @pytest.mark.asyncio
    async def test_prints_and_continues_on_storage_error(self, mocker):
        """
        A StorageError raised while persisting data must be caught and
        printed, without propagating out of the task (the task keeps
        running on schedule).
        """
        _patch_sleep_for_single_iteration(mocker)
        mocker.patch(
            "src.app._resolve_temperature_data",
            return_value=(23.5, "Good", "live"),
        )
        mocker.patch(
            "src.app.store_temperature_data",
            side_effect=StorageError("write failed"),
        )
        print_mock = mocker.patch("builtins.print")

        with pytest.raises(asyncio.CancelledError):
            await _periodic_store()

        print_mock.assert_any_call("Scheduled store failed: write failed")


# ---------------------------------------------------------------------------
# lifespan
# ---------------------------------------------------------------------------


class TestLifespan:
    """Tests for the lifespan() context manager."""

    @pytest.mark.asyncio
    async def test_starts_periodic_store_task_on_entry(self, mocker):
        """
        Entering the lifespan context must schedule _periodic_store as a
        background task and print a start message including the interval.
        """
        started = asyncio.Event()

        async def fake_periodic_store():
            started.set()
            await asyncio.Event().wait()

        mocker.patch("src.app._periodic_store", side_effect=fake_periodic_store)
        print_mock = mocker.patch("builtins.print")

        async with lifespan(None):
            await asyncio.wait_for(started.wait(), timeout=1)

        print_mock.assert_any_call(
            f"Periodic store task started (interval: {STORE_INTERVAL_SECONDS} s)"
        )

    @pytest.mark.asyncio
    async def test_cancels_and_awaits_task_on_exit(self, mocker):
        """
        Exiting the lifespan context must cancel the background task,
        await its completion, swallow the resulting CancelledError, and
        print a stop message.
        """
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_periodic_store():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        mocker.patch("src.app._periodic_store", side_effect=fake_periodic_store)
        print_mock = mocker.patch("builtins.print")

        async with lifespan(None):
            await asyncio.wait_for(started.wait(), timeout=1)

        assert cancelled.is_set()
        print_mock.assert_any_call("Periodic store task stopped")


# ---------------------------------------------------------------------------
# GET /temperature
# ---------------------------------------------------------------------------


class TestTemperatureEndpoint:
    """Unit tests for the /temperature endpoint."""

    def test_returns_data_with_cache_source(self, mocker):
        """
        Returns temperature data with source="cache" when
        _resolve_temperature_data reports a cache hit.
        """
        mocker.patch(
            "src.app._resolve_temperature_data",
            return_value=(23.5, "Good", "cache"),
        )

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json() == {
            "average_temperature": 23.5,
            "status": "Good",
            "source": "cache",
        }

    def test_returns_data_with_live_source(self, mocker):
        """
        Returns temperature data with source="live" when
        _resolve_temperature_data reports a live reading.
        """
        mocker.patch(
            "src.app._resolve_temperature_data",
            return_value=(23.5, "Good", "live"),
        )

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json() == {
            "average_temperature": 23.5,
            "status": "Good",
            "source": "live",
        }

    def test_returns_503_when_no_data_available(self, mocker):
        """
        Responds with 503 when _resolve_temperature_data returns None.
        """
        mocker.patch("src.app._resolve_temperature_data", return_value=None)

        response = client.get("/temperature")

        assert response.status_code == 503
        assert response.json() == {"detail": "No recent temperature data"}
