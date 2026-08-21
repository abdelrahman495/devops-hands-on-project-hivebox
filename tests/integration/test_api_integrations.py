"""
Integration tests for the HiveBox FastAPI application.

This module verifies the full request/response cycle for each API endpoint,
as well as the periodic store background task exercised through the app's
real lifespan via a context-managed TestClient rather than calling the
background coroutine directly. These tests use the `responses` library to
intercept outbound HTTP calls to the openSenseMap API and mock Valkey and
MinIO calls, allowing the complete application stack to execute against
controlled external data without requiring real network access, live
senseBox devices, or running Valkey and MinIO instances.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest
import responses
from fastapi.testclient import TestClient

from src.app import __version__, app
from src.sensebox_service import BASE_URL, SENSEBOX_IDS
from src.storage_service import StorageError
from tests.helpers.prometheus import metric_value

client = TestClient(app)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_box_payload(box_id: str, temperature: float, minutes_ago: int = 10) -> dict:
    """
    Builds a minimal openSenseMap box JSON payload containing a single
    temperature sensor whose last measurement is `minutes_ago` minutes old.

    Args:
        box_id (str): The senseBox identifier embedded in the payload.
        temperature (float): The temperature value to include.
        minutes_ago (int): How many minutes in the past the measurement was taken.
            Values ≤ 60 produce a "recent" reading; values > 60 produce a stale one.

    Returns:
        dict: A dict that mirrors the structure returned by the openSenseMap API.
    """
    timestamp = datetime.now(UTC) - timedelta(minutes=minutes_ago)

    return {
        "_id": box_id,
        "sensors": [
            {
                "title": "Temperatur",
                "lastMeasurement": {
                    "value": str(temperature),
                    "createdAt": (
                        timestamp.isoformat(timespec="milliseconds").replace(
                            "+00:00", "Z"
                        )
                    ),
                },
            }
        ],
    }


def _register_box_responses(
    box_data: list[tuple[float, int]] | list[float], minutes_ago: int = 10
) -> None:
    """
    Registers mock HTTP responses for every SENSEBOX_ID. Each box
    can be configured with a temperature and a measurement age.
    If fewer temperatures than boxes are supplied the remaining boxes
    receive an HTTP 500 response (simulating an unavailable device).

    Args:
        box_data (list[tuple[float, int]] | list[float]): Either a list of
            (temperature, minutes_ago) tuples for per-box control, or a plain
            list of floats to apply the same `minutes_ago` to all boxes.
        minutes_ago (int): Fallback age in minutes, used only when `box_data`
            contains plain floats rather than tuples.
    """
    for index, box_id in enumerate(SENSEBOX_IDS):
        url = f"{BASE_URL}/{box_id}"

        if index < len(box_data):
            entry = box_data[index]
            temp, age = entry if isinstance(entry, tuple) else (entry, minutes_ago)
            responses.add(
                responses.GET,
                url,
                json=_make_box_payload(box_id, temp, age),
                status=200,
            )
        else:
            responses.add(
                responses.GET,
                url,
                status=500,
            )


def _wait_until(condition, timeout: float = 2.0, interval: float = 0.01) -> None:
    """
    Polls `condition` (a zero-arg callable) until it returns truthy or the
    timeout elapses.

    Used to observe the periodic store background task's effects from
    synchronous test code: the task runs concurrently on the TestClient's
    own event loop thread, so there's no single call to await inline the
    way there is for a normal endpoint request.

    Raises:
        AssertionError: If `condition` never becomes truthy within `timeout`.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        if condition():
            return
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")


# ---------------------------------------------------------------------------
# Metrics set at import time
# ---------------------------------------------------------------------------


def test_app_info_metric_reflects_running_version():
    """
    Verifies the hivebox_app_info metric exposes the running app's version.
    """
    assert metric_value("hivebox_app_info", version=__version__) == 1


def test_sensebox_boxes_configured_metric():
    """
    Verifies the configured senseBox count metric matches SENSEBOX_IDS.
    """
    assert metric_value("hivebox_sensebox_boxes_configured") == len(SENSEBOX_IDS)


# ---------------------------------------------------------------------------
# Periodic store background task (via app lifespan)
# ---------------------------------------------------------------------------


class TestPeriodicStoreIntegration:
    """Integration tests for the periodic store background task."""

    @responses.activate
    def test_persists_cached_snapshot_through_real_lifespan(self, mocker):
        """
        With a short store interval, starting the app must trigger the
        periodic task, which resolves a cached reading through the real
        cache-first resolver (without hitting the mocked senseBox API)
        and persists it with the correct averaged temperature and status.
        """
        mocker.patch("src.app.is_cache_stale", return_value=False)
        mocker.patch(
            "src.app.get_temperature_cache",
            return_value={"average_temperature": 23.5, "status": "Good"},
        )
        mocker.patch("src.app.STORE_INTERVAL_SECONDS", 0.01)
        store_mock = mocker.patch(
            "src.app.store_temperature_data",
            return_value="temperatures/fake.json",
        )

        with TestClient(app):
            _wait_until(lambda: store_mock.call_count >= 1)

        avg_temp, status = store_mock.call_args.args
        assert avg_temp == pytest.approx(23.5, abs=1e-2)
        assert status == "Good"

    @responses.activate
    def test_persists_live_snapshot_through_real_lifespan(self, mocker):
        """
        With a short store interval, starting the app must trigger the
        periodic task, which resolves a live reading through the real
        cache-first resolver (hitting the mocked senseBox API) and
        persists it with the correct averaged temperature and status.
        """
        _register_box_responses([20.0, 22.0, 24.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch("src.app.STORE_INTERVAL_SECONDS", 0.01)
        store_mock = mocker.patch(
            "src.app.store_temperature_data",
            return_value="temperatures/fake.json",
        )

        with TestClient(app):
            _wait_until(lambda: store_mock.call_count >= 1)

        avg_temp, status = store_mock.call_args.args
        assert avg_temp == pytest.approx(22.0, abs=1e-2)
        assert status == "Good"

    @responses.activate
    def test_task_stops_persisting_after_shutdown(self, mocker):
        """
        Once the app's lifespan exits, the periodic task must be
        cancelled and stop calling store_temperature_data; no
        further snapshots are persisted after shutdown.
        """
        _register_box_responses([20.0, 22.0, 24.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch("src.app.STORE_INTERVAL_SECONDS", 0.01)
        store_mock = mocker.patch(
            "src.app.store_temperature_data",
            return_value="temperatures/fake.json",
        )

        with TestClient(app):
            _wait_until(lambda: store_mock.call_count >= 1)

        call_count_at_shutdown = store_mock.call_count
        time.sleep(0.1)  # several intervals' worth of real time

        assert store_mock.call_count == call_count_at_shutdown


# ---------------------------------------------------------------------------
# GET /metrics
# ---------------------------------------------------------------------------


def test_metrics_endpoint():
    """
    Tests the /metrics endpoint.

    A request to /version is made first to ensure at least one request
    has been instrumented. The test then verifies that the endpoint
    responds with HTTP 200, returns plain text content in the expected
    Prometheus exposition format, and that the metrics output includes
    both the standard python_info metric and a reference to /version,
    confirming per-endpoint tracking is active.
    """
    client.get("/version")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "python_info" in response.text
    assert "/version" in response.text


# ---------------------------------------------------------------------------
# GET /version
# ---------------------------------------------------------------------------


def test_version_endpoint():
    """
    Tests the /version endpoint.

    The test verifies that the endpoint responds with HTTP 200
    and that the returned JSON payload contains the correct
    'version' value.
    """
    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["version"] == __version__


# ---------------------------------------------------------------------------
# GET /temperature
# ---------------------------------------------------------------------------


class TestTemperatureEndpoint:
    """Integration tests for the /temperature endpoint."""

    @responses.activate
    def test_returns_200_and_cached_data_when_cache_is_fresh(self, mocker):
        """
        Verifies that GET /temperature responds with HTTP 200 and
        source="cache" when the cache is fresh. No box responses are
        registered here, so if the endpoint incorrectly fell through
        to the live senseBox API, the unmocked outbound request would
        fail loudly (via `responses`) rather than the test passing
        by coincidence.
        """
        mocker.patch("src.app.is_cache_stale", return_value=False)
        mocker.patch(
            "src.app.get_temperature_cache",
            return_value={"average_temperature": 23.5, "status": "Good"},
        )

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json() == {
            "average_temperature": 23.5,
            "status": "Good",
            "source": "cache",
        }

    @responses.activate
    def test_returns_200_and_live_data_when_no_cache_entry(self, mocker):
        """
        Verifies that GET /temperature responds with HTTP 200 and
        source="live" when the cache is stale and openSenseMap API
        returns valid, recent temperature readings.
        """
        _register_box_responses([20.0, 22.0, 24.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json()["source"] == "live"

    @responses.activate
    def test_average_temperature_is_computed_correctly(self, mocker):
        """
        Verifies that the returned average temperature is the arithmetic mean
        of the mock sensor values, rounded to two decimal places.
        """
        _register_box_responses([20.0, 21.0, 23.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.json()["average_temperature"] == pytest.approx(21.33, abs=1e-2)
        assert (
            metric_value("hivebox_sensebox_temperature_average_celsius")
            == response.json()["average_temperature"]
        )

    @responses.activate
    def test_status_is_good_for_moderate_temperature(self, mocker):
        """
        Verifies that a temperature between 10 °C and 37 °C yields the
        'Good' status label.
        """
        _register_box_responses([9.0, 24.0, 38.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.json()["status"] == "Good"
        assert metric_value("hivebox_temperature_status", status="Too Cold") == 0
        assert metric_value("hivebox_temperature_status", status="Good") == 1
        assert metric_value("hivebox_temperature_status", status="Too Hot") == 0

    @responses.activate
    def test_status_is_too_cold_below_10(self, mocker):
        """
        Verifies that an average temperature below 10 °C yields the
        'Too Cold' status label.
        """
        _register_box_responses([8.0, 9.0, 12.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.json()["status"] == "Too Cold"
        assert metric_value("hivebox_temperature_status", status="Too Cold") == 1
        assert metric_value("hivebox_temperature_status", status="Good") == 0
        assert metric_value("hivebox_temperature_status", status="Too Hot") == 0

    @responses.activate
    def test_status_is_too_hot_above_37(self, mocker):
        """
        Verifies that an average temperature above 37 °C yields the
        'Too Hot' status label.
        """
        _register_box_responses([26.0, 45.0, 41.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")

        response = client.get("/temperature")

        assert response.json()["status"] == "Too Hot"
        assert metric_value("hivebox_temperature_status", status="Too Cold") == 0
        assert metric_value("hivebox_temperature_status", status="Good") == 0
        assert metric_value("hivebox_temperature_status", status="Too Hot") == 1

    @responses.activate
    def test_returns_503_when_all_boxes_unavailable(self, mocker):
        """
        Verifies that GET /temperature responds with HTTP 503 when every
        openSenseMap request fails (no temperatures can be retrieved).
        """
        _register_box_responses([])  # no box data → all boxes return HTTP 500
        mocker.patch("src.app.is_cache_stale", return_value=True)

        response = client.get("/temperature")

        assert response.status_code == 503

    @responses.activate
    def test_returns_503_when_all_measurements_are_stale(self, mocker):
        """
        Verifies that GET /temperature responds with HTTP 503 when all sensor
        readings are older than one hour and therefore discarded.
        """
        _register_box_responses([20.0, 22.0, 24.0], minutes_ago=90)
        mocker.patch("src.app.is_cache_stale", return_value=True)

        response = client.get("/temperature")

        assert response.status_code == 503

    @responses.activate
    def test_partial_box_failure_still_returns_200(self, mocker):
        """
        Verifies that the endpoint succeeds when at least one senseBox returns
        valid data, even if the remaining boxes are unavailable. Only the
        first box receives a successful mock response here.
        """
        _register_box_responses([21.0])  # remaining boxes get HTTP 500
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        success_box_id, failure_box_id = SENSEBOX_IDS[0], SENSEBOX_IDS[1]
        success_duration_count_before = metric_value(
            "hivebox_sensebox_request_duration_seconds_count", box_id=success_box_id
        )
        failure_duration_count_before = metric_value(
            "hivebox_sensebox_request_duration_seconds_count", box_id=failure_box_id
        )
        success_requests_before = metric_value(
            "hivebox_sensebox_requests_total", box_id=success_box_id, outcome="success"
        )
        failure_requests_before = metric_value(
            "hivebox_sensebox_requests_total", box_id=failure_box_id, outcome="failure"
        )

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json()["average_temperature"] == pytest.approx(21.0, abs=1e-2)
        assert (
            metric_value(
                "hivebox_sensebox_request_duration_seconds_count", box_id=success_box_id
            )
            == success_duration_count_before + 1
        )
        assert (
            metric_value(
                "hivebox_sensebox_request_duration_seconds_count", box_id=failure_box_id
            )
            == failure_duration_count_before + 1
        )
        assert (
            metric_value(
                "hivebox_sensebox_requests_total",
                box_id=success_box_id,
                outcome="success",
            )
            == success_requests_before + 1
        )
        assert (
            metric_value(
                "hivebox_sensebox_requests_total",
                box_id=failure_box_id,
                outcome="failure",
            )
            == failure_requests_before + 1
        )
        assert (
            metric_value("hivebox_sensebox_boxes_contributing", box_id=failure_box_id)
            == 0
        )

    @responses.activate
    def test_mixed_fresh_and_stale_measurements(self, mocker):
        """
        Stale readings must be ignored; the average is computed only from fresh
        measurements.
        """
        _register_box_responses([(20.0, 10), (30.0, 90), (24.0, 10)])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        fresh_box_id, stale_box_id = SENSEBOX_IDS[0], SENSEBOX_IDS[1]

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json()["average_temperature"] == pytest.approx(
            22.0, abs=1e-2
        )  # (20 + 24) / 2
        assert (
            metric_value("hivebox_sensebox_boxes_contributing", box_id=fresh_box_id)
            == 1
        )
        assert (
            metric_value("hivebox_sensebox_boxes_contributing", box_id=stale_box_id)
            == 0
        )


# ---------------------------------------------------------------------------
# GET /store
# ---------------------------------------------------------------------------


class TestStoreEndpoint:
    """Integration tests for the /store endpoint."""

    @responses.activate
    def test_stores_from_cache_when_cache_is_fresh(self, mocker):
        """
        Verifies that GET /store persists cached data and responds with
        HTTP 200 and source="cache" when the cache is fresh. No box
        responses are registered here, so if the endpoint incorrectly
        fell through to the live senseBox API, the unmocked outbound
        request would fail loudly (via `responses`) rather than the
        test passing by coincidence.
        """
        mocker.patch("src.app.is_cache_stale", return_value=False)
        mocker.patch(
            "src.app.get_temperature_cache",
            return_value={"average_temperature": 23.5, "status": "Good"},
        )
        mocker.patch(
            "src.app.store_temperature_data",
            return_value="temperatures/fake.json",
        )

        response = client.get("/store")

        assert response.status_code == 200
        assert response.json() == {
            "object": "temperatures/fake.json",
            "source": "cache",
        }

    @responses.activate
    def test_stores_from_live_api_when_cache_is_stale(self, mocker):
        """
        Verifies that GET /store persists live data and responds with
        HTTP 200 and source="live" when the cache is stale and
        openSenseMap API returns valid, recent temperature readings.
        """
        _register_box_responses([20.0, 22.0, 24.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch(
            "src.app.store_temperature_data",
            return_value="temperatures/fake.json",
        )

        response = client.get("/store")

        assert response.status_code == 200
        assert response.json() == {
            "object": "temperatures/fake.json",
            "source": "live",
        }

    @responses.activate
    def test_returns_503_when_cache_stale_and_no_boxes_available(self, mocker):
        """
        Verifies that GET /store responds with HTTP 503 when
        cache is stale and all boxes are unreachable.
        """
        _register_box_responses([])  # no box data → all boxes return HTTP 500
        mocker.patch("src.app.is_cache_stale", return_value=True)

        response = client.get("/store")

        assert response.status_code == 503

    @responses.activate
    def test_returns_500_when_minio_write_fails(self, mocker):
        """
        Verifies that GET /store responds with HTTP 500 when
        store_temperature_data raises StorageError.
        """
        _register_box_responses([20.0, 22.0, 24.0])
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch(
            "src.app.store_temperature_data",
            side_effect=StorageError("MinIO connection refused"),
        )

        response = client.get("/store")

        assert response.status_code == 500


# ---------------------------------------------------------------------------
# GET /readyz
# ---------------------------------------------------------------------------


class TestReadyzEndpoint:
    """Integration tests for the /readyz endpoint."""

    @responses.activate
    def test_returns_200_when_cache_is_stale_but_no_boxes_queried(self, mocker):
        """
        Verifies that GET /readyz responds with HTTP 200 when the cache is
        stale but no senseBox has been probed yet. No box responses are
        registered here, so if the endpoint made a live call to check box
        reachability, the unmocked outbound request would fail loudly
        (via `responses`) rather than the test passing by coincidence.
        """
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch.dict("src.sensebox_service._accessibility", {}, clear=True)

        response = client.get("/readyz")

        assert response.status_code == 200

    @responses.activate
    def test_returns_200_when_cache_is_fresh(self, mocker):
        """
        Verifies that GET /readyz responds with HTTP 200 when the cache is
        fresh, even though every configured senseBox is recorded as
        inaccessible. A fresh cache must short-circuit the box check entirely,
        so the readiness verdict depends only on cache staleness here.
        """
        mocker.patch("src.app.is_cache_stale", return_value=False)
        mocker.patch.dict(
            "src.sensebox_service._accessibility",
            {box_id: False for box_id in SENSEBOX_IDS},
            clear=True,
        )

        response = client.get("/readyz")

        assert response.status_code == 200

    @responses.activate
    def test_returns_200_when_cache_is_stale_but_all_boxes_accessible(self, mocker):
        """
        Verifies that GET /readyz responds with HTTP 200 when the cache is
        stale and a prior live resolution recorded every configured senseBox
        as accessible.
        """
        _register_box_responses([21.0] * len(SENSEBOX_IDS))
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch.dict("src.sensebox_service._accessibility", {}, clear=True)

        client.get("/temperature")

        response = client.get("/readyz")

        assert response.status_code == 200
        for box_id in SENSEBOX_IDS:
            assert metric_value("hivebox_sensebox_boxes_accessible", box_id=box_id) == 1

    @responses.activate
    def test_returns_200_when_cache_is_stale_but_majority_of_boxes_accessible(
        self, mocker
    ):
        """
        Verifies that GET /readyz responds with HTTP 200 when the cache is
        stale and the number of inaccessible senseBoxes is exactly one short
        of the 50% + 1 majority-down threshold, with the remainder accessible.
        """
        total_boxes = len(SENSEBOX_IDS)
        majority_threshold = total_boxes // 2 + 1
        accessible_count = total_boxes - (majority_threshold - 1)

        _register_box_responses(
            [21.0] * accessible_count
        )  # remaining boxes get HTTP 500
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch.dict("src.sensebox_service._accessibility", {}, clear=True)

        client.get("/temperature")

        response = client.get("/readyz")

        assert response.status_code == 200
        for index, box_id in enumerate(SENSEBOX_IDS):
            if index < accessible_count:
                assert (
                    metric_value("hivebox_sensebox_boxes_accessible", box_id=box_id)
                    == 1
                )
            else:
                assert (
                    metric_value("hivebox_sensebox_boxes_accessible", box_id=box_id)
                    == 0
                )

    @responses.activate
    def test_returns_503_when_cache_is_stale_and_majority_of_boxes_inaccessible(
        self, mocker
    ):
        """
        Verifies that GET /readyz responds with HTTP 503 and the expected
        error detail when the cache is stale and the number of inaccessible
        senseBoxes exactly meets the 50% + 1 majority-down threshold.
        """
        total_boxes = len(SENSEBOX_IDS)
        majority_threshold = total_boxes // 2 + 1
        accessible_count = total_boxes - majority_threshold

        _register_box_responses(
            [21.0] * accessible_count
        )  # remaining boxes get HTTP 500
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch("src.app.set_temperature_cache")
        mocker.patch.dict("src.sensebox_service._accessibility", {}, clear=True)

        client.get("/temperature")

        response = client.get("/readyz")

        assert response.status_code == 503
        assert response.json() == {"detail": "Application is not ready"}
        for index, box_id in enumerate(SENSEBOX_IDS):
            if index < accessible_count:
                assert (
                    metric_value("hivebox_sensebox_boxes_accessible", box_id=box_id)
                    == 1
                )
            else:
                assert (
                    metric_value("hivebox_sensebox_boxes_accessible", box_id=box_id)
                    == 0
                )

    @responses.activate
    def test_returns_503_when_cache_is_stale_and_all_boxes_inaccessible(self, mocker):
        """
        Verifies that GET /readyz responds with HTTP 503 and the expected
        error detail when the cache is stale and every configured senseBox
        is inaccessible.
        """
        _register_box_responses([])  # no box data → all boxes return HTTP 500
        mocker.patch("src.app.is_cache_stale", return_value=True)
        mocker.patch.dict("src.sensebox_service._accessibility", {}, clear=True)

        client.get("/temperature")

        response = client.get("/readyz")

        assert response.status_code == 503
        assert response.json() == {"detail": "Application is not ready"}
        for box_id in SENSEBOX_IDS:
            assert metric_value("hivebox_sensebox_boxes_accessible", box_id=box_id) == 0
