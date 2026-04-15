"""
Integration tests for the HiveBox FastAPI application.

This module verifies the full request/response cycle for each API endpoint.
Unlike unit tests, these tests do not mock internal functions. Instead,
they use the `responses` library to intercept outbound HTTP calls to the
openSenseMap API, allowing the complete application stack — routing,
service logic, and temperature utilities — to execute against controlled
external data without requiring real network access or live senseBox devices.
"""

from datetime import datetime, timedelta, timezone

import pytest
import responses
from fastapi.testclient import TestClient

from app import app, __version__
from sensebox_service import BASE_URL, SENSEBOX_IDS

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
    timestamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)

    return {
        "_id": box_id,
        "sensors": [
            {
                "title": "Temperatur",
                "lastMeasurement": {
                    "value": str(temperature),
                    "createdAt": (
                        timestamp
                        .isoformat(timespec="milliseconds")
                        .replace("+00:00", "Z")
                    ),
                },
            }
        ],
    }


def _register_box_responses(
        box_data: list[tuple[float, int]] | list[float],
        minutes_ago: int = 10
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
    def test_returns_200_when_data_available(self):
        """
        Verifies that GET /temperature responds with HTTP 200 when the
        openSenseMap API returns valid, recent temperature readings.
        """
        _register_box_responses([20.0, 22.0, 24.0])

        response = client.get("/temperature")

        assert response.status_code == 200

    @responses.activate
    def test_average_temperature_is_computed_correctly(self):
        """
        Verifies that the returned average temperature is the arithmetic mean
        of the mock sensor values, rounded to two decimal places.
        """
        _register_box_responses([20.0, 21.0, 23.0])

        response = client.get("/temperature")

        assert response.json()["average_temperature"] == 21.33

    @responses.activate
    def test_status_is_good_for_moderate_temperature(self):
        """
        Verifies that a temperature between 10 °C and 37 °C yields the
        'Good' status label.
        """
        _register_box_responses([9.0, 24.0, 38.0])

        response = client.get("/temperature")

        assert response.json()["status"] == "Good"

    @responses.activate
    def test_status_is_too_cold_below_10(self):
        """
        Verifies that an average temperature below 10 °C yields the
        'Too Cold' status label.
        """
        _register_box_responses([8.0, 9.0, 12.0])

        response = client.get("/temperature")

        assert response.json()["status"] == "Too Cold"

    @responses.activate
    def test_status_is_too_hot_above_37(self):
        """
        Verifies that an average temperature above 37 °C yields the
        'Too Hot' status label.
        """
        _register_box_responses([26.0, 45.0, 41.0])

        response = client.get("/temperature")

        assert response.json()["status"] == "Too Hot"

    @responses.activate
    def test_returns_503_when_all_boxes_unavailable(self):
        """
        Verifies that GET /temperature responds with HTTP 503 when every
        openSenseMap request fails (no temperatures can be retrieved).
        """
        _register_box_responses([])  # no box data → all boxes return HTTP 500

        response = client.get("/temperature")

        assert response.status_code == 503

    @responses.activate
    def test_returns_503_when_all_measurements_are_stale(self):
        """
        Verifies that GET /temperature responds with HTTP 503 when all sensor
        readings are older than one hour and therefore discarded.
        """
        _register_box_responses([20.0, 22.0, 24.0], minutes_ago=90)

        response = client.get("/temperature")

        assert response.status_code == 503

    @responses.activate
    def test_partial_box_failure_still_returns_200(self):
        """
        Verifies that the endpoint succeeds when at least one senseBox returns
        valid data, even if the remaining boxes are unavailable. Only the
        first box receives a successful mock response here.
        """
        _register_box_responses([21.0])  # remaining boxes get HTTP 500

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json()["average_temperature"] == pytest.approx(21.0, abs=0.01)

    @responses.activate
    def test_mixed_fresh_and_stale_measurements(self):
        """
        Stale readings must be ignored; the average is computed only from fresh
        measurements.
        """
        _register_box_responses([(20.0, 10), (30.0, 90), (24.0, 10)])

        response = client.get("/temperature")

        assert response.status_code == 200
        assert response.json()["average_temperature"] == 22.0  # (20 + 24) / 2
