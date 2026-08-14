"""
Utility module for interpreting temperature data.
"""

from src.metrics import TEMPERATURE_STATUS

STATUS_LABELS = ("Too Cold", "Good", "Too Hot")


def get_temperature_status(temp):
    """
    Determines the status label for a given temperature value.

    Args:
        temp (float): The temperature value in degrees Celsius.

    Returns:
        str:
            A status string based on the temperature value:
            "Too Cold" if below 10, "Good" if between 10 and 37
            inclusive, or "Too Hot" if above 37.
    """
    if temp < 10:
        status = STATUS_LABELS[0]
    elif temp <= 37:
        status = STATUS_LABELS[1]
    else:
        status = STATUS_LABELS[2]

    for label in STATUS_LABELS:
        TEMPERATURE_STATUS.labels(status=label).set(1 if label == status else 0)

    return status
