"""
Cache service using Valkey (Redis-compatible) for storing temperature snapshots.

Provides set/get/age helpers for caching temperature data with a 5-minute TTL.
"""

import json
import os
import time

from valkey import Valkey, ValkeyError

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))

TEMPERATURE_CACHE_KEY = "hivebox:temperature"
CACHE_TTL = 300

_client = None


def get_client():
    """
    Returns a lazily-initialized singleton Valkey client.
    """
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = Valkey(
            host=VALKEY_HOST,
            port=VALKEY_PORT,
            decode_responses=True,
        )
    return _client


def set_temperature_cache(avg_temp, status):
    """
    Stores temperature data in Valkey with a `CACHE_TTL` TTL.

    Args:
        avg_temp (float): The average temperature value in Celsius.
        status (str): The human-readable temperature status (e.g. "Good").
    """
    client = get_client()
    payload = json.dumps(
        {
            "average_temperature": avg_temp,
            "status": status,
            "cached_at": time.time(),
        }
    )

    try:
        client.setex(TEMPERATURE_CACHE_KEY, CACHE_TTL, payload)
    except ValkeyError as exc:
        print(f"Failed to write to Valkey cache: {exc}")


def get_temperature_cache():
    """
    Retrieves the latest cached temperature entry from Valkey.

    Returns:
        dict | None:
            A dict with keys `average_temperature`, `status`, and
            `cached_at` when a cache entry exists, otherwise None.
    """
    client = get_client()

    try:
        raw = client.get(TEMPERATURE_CACHE_KEY)
        if raw is not None:
            return json.loads(raw)
    except ValkeyError as exc:
        print(f"Failed to read from Valkey cache: {exc}")
    return None


def get_cache_age_seconds():
    """
    Returns how many seconds ago the temperature cache was written.

    Returns:
        float | None:
            Elapsed seconds as a float, or None when no entry is cached.
    """
    data = get_temperature_cache()
    if data is None:
        return None
    return time.time() - data["cached_at"]


def is_cache_stale(max_age_seconds=CACHE_TTL):
    """
    Determines whether the cached temperature data is considered stale.

    Args:
        max_age_seconds (float): Maximum acceptable cache age. Defaults to `CACHE_TTL`
                         (300 s / 5 min).

    Returns:
        bool:
            True when the cache is absent or older than `max_age_seconds`.
    """
    age = get_cache_age_seconds()
    return age is None or age > max_age_seconds
