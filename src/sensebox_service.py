"""
Service module responsible for interacting with the openSenseMap API and
computing the average temperature from a predefined set of senseBox devices.

The module fetches sensor data from the openSenseMap API, extracts recent
temperature measurements (not older than one hour), and computes their average.
"""

from datetime import UTC, datetime, timedelta

import requests

from src.metrics import (
    SENSEBOX_BOXES_ACCESSIBLE,
    SENSEBOX_BOXES_CONFIGURED,
    SENSEBOX_BOXES_CONTRIBUTING,
    SENSEBOX_REQUEST_DURATION,
    SENSEBOX_REQUESTS,
    SENSEBOX_TEMPERATURE_AVERAGE,
)

with open("config/sensebox_ids.txt", "r", encoding="utf-8") as f:
    SENSEBOX_IDS = f.read().strip().split("\n")

SENSEBOX_BOXES_CONFIGURED.set(len(SENSEBOX_IDS))

BASE_URL = "https://api.opensensemap.org/boxes"

_accessibility = {}


def _record_accessibility(box_id, accessible):
    """
    Records the reachability outcome of a live request to `box_id`, both in
    the in-memory map consulted by is_majority_down() and in the corresponding
    Prometheus gauge.
    """
    _accessibility[box_id] = accessible
    SENSEBOX_BOXES_ACCESSIBLE.labels(box_id=box_id).set(1 if accessible else 0)


def get_box_data(box_id):
    """
    Fetches data for a specific senseBox from the openSenseMap API.

    Args:
        box_id (str): The unique identifier of the senseBox.

    Returns:
        dict | None:
            Parsed JSON response containing the senseBox data
            if the request is successful, otherwise None.
    """
    with SENSEBOX_REQUEST_DURATION.labels(box_id=box_id).time():
        response = requests.get(f"{BASE_URL}/{box_id}", timeout=10)

    if response.status_code != 200:
        _record_accessibility(box_id, accessible=False)
        SENSEBOX_REQUESTS.labels(box_id=box_id, outcome="failure").inc()
        return None

    _record_accessibility(box_id, accessible=True)
    SENSEBOX_REQUESTS.labels(box_id=box_id, outcome="success").inc()
    return response.json()


def extract_temperature(box_data):
    """
    Extracts recent temperature measurements from a senseBox dataset.

    This function scans the sensors of the provided senseBox data,
    identifies temperature sensors, and collects temperature values
    whose timestamps are not older than one hour.

    Args:
        box_data (dict): JSON data representing a senseBox.

    Returns:
        list[float]:
            A list of temperature values that were measured within the last hour.
    """
    temps = []

    sensors = box_data.get("sensors", [])

    for sensor in sensors:
        title = sensor.get("title")

        if title == "Temperatur":
            measurement = sensor.get("lastMeasurement")

            if not measurement:
                continue

            value = float(measurement["value"])
            timestamp = datetime.fromisoformat(measurement["createdAt"])

            now = datetime.now(UTC)

            if now - timestamp <= timedelta(hours=1):
                temps.append(value)

    return temps


def get_average_temperature():
    """
    Calculates the average temperature from multiple senseBoxes.

    The function retrieves data from predefined senseBox IDs,
    extracts recent temperature measurements from each box,
    and computes the average temperature.

    Returns:
        float | None:
            The average temperature rounded to two decimal places
            if valid measurements exist, otherwise None.
    """

    temperatures = []

    for box_id in SENSEBOX_IDS:
        data = get_box_data(box_id)

        if not data:
            SENSEBOX_BOXES_CONTRIBUTING.labels(box_id=box_id).set(0)
            continue

        temps = extract_temperature(data)

        SENSEBOX_BOXES_CONTRIBUTING.labels(box_id=box_id).set(1 if temps else 0)

        temperatures.extend(temps)

    if not temperatures:
        return None

    avg_temp = round(sum(temperatures) / len(temperatures), 2)

    SENSEBOX_TEMPERATURE_AVERAGE.set(avg_temp)

    return avg_temp


def is_majority_down():
    """
    Checks whether more than half (50% + 1) of the configured senseBoxes are
    currently inaccessible.

    Returns:
        bool:
            True when the number of inaccessible senseBoxes reaches the
            50% + 1 threshold, False otherwise (including when no
            senseBoxes are configured at all).
    """
    total_boxes = len(SENSEBOX_IDS)
    inaccessible_count = sum(
        1 for box_id in SENSEBOX_IDS if _accessibility.get(box_id) is False
    )
    majority_threshold = total_boxes // 2 + 1

    return inaccessible_count >= majority_threshold
