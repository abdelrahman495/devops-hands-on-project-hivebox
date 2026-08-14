"""
Custom Prometheus metrics for the HiveBox application.

These are collected alongside the default FastAPI/process metrics already
exposed by `prometheus-fastapi-instrumentator`.
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

APP_INFO = Info(
    "hivebox_app",
    "Build/version metadata for the running HiveBox instance",
)

TEMPERATURE_RESOLUTION_DURATION = Histogram(
    "hivebox_temperature_resolution_duration_seconds",
    "Duration of temperature resolutions, by source",
    ["source"],  # cache | live
)

TEMPERATURE_RESOLUTIONS = Counter(
    "hivebox_temperature_resolutions_total",
    "Number of times temperature data was successfully resolved, by source",
    ["source"],  # cache | live
)

TEMPERATURE_RESOLUTION_LAST_SUCCESS_TIMESTAMP = Gauge(
    "hivebox_temperature_resolution_last_success_timestamp_seconds",
    "Unix timestamp of the last successful temperature resolution operation",
)

TEMPERATURE_RESOLUTION_FAILURES = Counter(
    "hivebox_temperature_resolution_failures_total",
    "Number of times temperature resolution failed (no cache and no live data)",
)

PERIODIC_STORE_LAST_ATTEMPT_TIMESTAMP = Gauge(
    "hivebox_periodic_store_last_attempt_timestamp_seconds",
    "Unix timestamp of the last attempt to perform periodic store operation",
)

PERIODIC_STORE_LAST_SUCCESS_TIMESTAMP = Gauge(
    "hivebox_periodic_store_last_success_timestamp_seconds",
    "Unix timestamp of the last successful periodic store operation",
)

STORE_OPERATIONS = Counter(
    "hivebox_store_operations_total",
    "Number of store operations, by trigger and outcome",
    [
        "trigger",
        "outcome",
    ],  # trigger: periodic|manual - outcome: success|no_data|failure
)

# ---------------------------------------------------------------------------
# API (openSenseMap)
# ---------------------------------------------------------------------------

SENSEBOX_BOXES_CONFIGURED = Gauge(
    "hivebox_sensebox_boxes_configured",
    "Number of senseBoxes configured in configs/sensebox_ids.txt",
)

SENSEBOX_REQUEST_DURATION = Histogram(
    "hivebox_sensebox_request_duration_seconds",
    "Duration of requests made to the openSenseMap API, by box",
    ["box_id"],
)

SENSEBOX_REQUESTS = Counter(
    "hivebox_sensebox_requests_total",
    "Requests made to the openSenseMap API, by box and outcome",
    ["box_id", "outcome"],  # success | failure
)

SENSEBOX_BOXES_CONTRIBUTING = Gauge(
    "hivebox_sensebox_boxes_contributing",
    "1 for senseBoxes that contributed a valid, recent temperature reading "
    "in the most recent average calculation, 0 for the others",
    ["box_id"],
)

SENSEBOX_TEMPERATURE_AVERAGE = Gauge(
    "hivebox_sensebox_temperature_average_celsius",
    "Most recently calculated average temperature, in Celsius",
)

# ---------------------------------------------------------------------------
# Temperature utilities
# ---------------------------------------------------------------------------

TEMPERATURE_STATUS = Gauge(
    "hivebox_temperature_status",
    "1 for the currently active temperature status label, 0 for the others",
    ["status"],  # Too Cold | Good | Too Hot
)

# ---------------------------------------------------------------------------
# Cache (Valkey)
# ---------------------------------------------------------------------------

CACHE_WRITE_OPERATIONS = Counter(
    "hivebox_cache_write_operations_total",
    "Valkey cache write operations, by outcome",
    ["outcome"],  # success | failure
)

CACHE_LAST_WRITE_TIMESTAMP = Gauge(
    "hivebox_cache_last_write_timestamp_seconds",
    "Unix timestamp of the last successful Valkey cache write",
)

CACHE_READ_OPERATIONS = Counter(
    "hivebox_cache_read_operations_total",
    "Valkey cache read operations, by outcome",
    ["outcome"],  # hit | miss | failure
)

# ---------------------------------------------------------------------------
# Storage (MinIO)
# ---------------------------------------------------------------------------

STORAGE_OPERATION_DURATION = Histogram(
    "hivebox_storage_operation_duration_seconds",
    "Duration of MinIO operations",
)
