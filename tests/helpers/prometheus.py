"""
Test helpers for reading Prometheus metric values from the default registry.

Used across the unit and integration suites to assert on the custom metrics
defined in `src/metrics.py` without reaching into individual Counter/Gauge/
Histogram internals.
"""

from prometheus_client import REGISTRY


def metric_value(name, **labels):
    """
    Reads the current value of a metric sample from the default Prometheus
    registry.

    Args:
        name (str): The full exposed metric/sample name.
        **labels: Label names and values identifying the sample.
            Omit for unlabeled metrics.

    Returns:
        float:
            The sample's current value, or 0 if that label combination
            hasn't been observed yet.
    """
    return REGISTRY.get_sample_value(name, labels) or 0
