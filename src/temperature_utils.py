"""
Utility module for interpreting temperature data.
"""


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
        return "Too Cold"

    if temp <= 37:
        return "Good"

    return "Too Hot"
