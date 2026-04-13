"""
Service module responsible for interacting with the openSenseMap API and
computing the average temperature from a predefined set of senseBox devices.

The module fetches sensor data from the openSenseMap API, extracts recent
temperature measurements (not older than one hour), and computes their average.
"""

from datetime import datetime, timedelta, timezone
import os
import requests

SENSEBOX_IDS = os.getenv(
    "SENSEBOX_IDS",
    "5eba5fbad46fb8001b799786,5c21ff8f919bf8001adf2488,5ade1acf223bd80019a1011c"
).split(",")

BASE_URL = "https://api.opensensemap.org/boxes"

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
    response = requests.get(f"{BASE_URL}/{box_id}", timeout=10)

    if response.status_code != 200:
        return None

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
            timestamp = datetime.fromisoformat(
                measurement["createdAt"].replace("Z", "+00:00")
            )

            now = datetime.now(timezone.utc)

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
            continue

        temps = extract_temperature(data)

        temperatures.extend(temps)

    if not temperatures:
        return None

    return round(sum(temperatures) / len(temperatures), 2)
