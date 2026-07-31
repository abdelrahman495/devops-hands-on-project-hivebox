"""
Unit tests for the cache_service module.

All Valkey network calls are mocked so no running instance is required.
"""

import json
import time

import pytest
from valkey import ValkeyError

from src.cache_service import (
    CACHE_TTL,
    TEMPERATURE_CACHE_KEY,
    get_cache_age_seconds,
    get_temperature_cache,
    is_cache_stale,
    set_temperature_cache,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# set_temperature_cache
# ---------------------------------------------------------------------------


class TestSetTemperatureCache:
    """Tests for set_temperature_cache()."""

    def test_writes_correct_key_ttl_and_payload(self, mocker):
        """
        setex must be called once with the canonical key, TTL,
        and a payload containing the supplied temperature, status,
        and a cached_at timestamp.
        """
        mock_client = mocker.Mock()
        mocker.patch("src.cache_service.get_client", return_value=mock_client)

        before = time.time()
        set_temperature_cache(22.5, "Good")
        after = time.time()

        mock_client.setex.assert_called_once_with(
            TEMPERATURE_CACHE_KEY, CACHE_TTL, mocker.ANY
        )

        payload = mock_client.setex.call_args.args[2]
        data = json.loads(payload)

        assert data["average_temperature"] == 22.5
        assert data["status"] == "Good"
        assert before <= data["cached_at"] <= after

    def test_handles_valkey_error(self, mocker):
        """
        A ValkeyError during the write (e.g. connection refused) must be
        caught internally and surfaced as a print statement.
        """
        mock_client = mocker.Mock()
        mock_client.setex.side_effect = ValkeyError("connection refused")
        mocker.patch("src.cache_service.get_client", return_value=mock_client)
        mock_print = mocker.patch("builtins.print")

        set_temperature_cache(22.5, "Good")

        mock_print.assert_called_once_with(
            "Failed to write to Valkey cache: connection refused"
        )


# ---------------------------------------------------------------------------
# get_temperature_cache
# ---------------------------------------------------------------------------


class TestGetTemperatureCache:
    """Tests for get_temperature_cache()."""

    def test_returns_none_when_key_absent(self, mocker):
        """
        A cache miss must return None.
        """
        mock_client = mocker.Mock()
        mock_client.get.return_value = None
        mocker.patch("src.cache_service.get_client", return_value=mock_client)

        assert get_temperature_cache() is None

    def test_returns_parsed_dict_on_cache_hit(self, mocker):
        """
        A cache hit must return the deserialized dict.
        """
        cached = {
            "average_temperature": 23.0,
            "status": "Good",
            "cached_at": time.time(),
        }
        mock_client = mocker.Mock()
        mock_client.get.return_value = json.dumps(cached)
        mocker.patch("src.cache_service.get_client", return_value=mock_client)

        result = get_temperature_cache()

        assert result["average_temperature"] == 23.0
        assert result["status"] == "Good"
        assert "cached_at" in result

    def test_returns_none_on_valkey_error(self, mocker):
        """
        A ValkeyError during the read (e.g. connection refused) must be
        caught internally and surfaced as a plain cache miss (i.e. returns None).
        """
        mock_client = mocker.Mock()
        mock_client.get.side_effect = ValkeyError("connection refused")
        mocker.patch("src.cache_service.get_client", return_value=mock_client)
        mock_print = mocker.patch("builtins.print")

        assert get_temperature_cache() is None
        mock_print.assert_called_once_with(
            "Failed to read from Valkey cache: connection refused"
        )


# ---------------------------------------------------------------------------
# get_cache_age_seconds
# ---------------------------------------------------------------------------


class TestGetCacheAgeSeconds:
    """Tests for get_cache_age_seconds()."""

    def test_returns_none_when_no_cache(self, mocker):
        """
        When get_temperature_cache returns None (cache miss or error),
        get_cache_age_seconds must also return None.
        """
        mocker.patch("src.cache_service.get_temperature_cache", return_value=None)

        assert get_cache_age_seconds() is None

    def test_returns_approximate_age(self, mocker):
        """
        Age should be close to the elapsed time since cached_at.
        """
        cached_at = time.time() - 120  # 2 minutes ago
        mocker.patch(
            "src.cache_service.get_temperature_cache",
            return_value={
                "average_temperature": 20.0,
                "status": "Good",
                "cached_at": cached_at,
            },
        )

        expected_age = time.time() - cached_at
        age = get_cache_age_seconds()

        assert abs(age - expected_age) < 1.0  # allow 1 second tolerance


# ---------------------------------------------------------------------------
# is_cache_stale
# ---------------------------------------------------------------------------


class TestIsCacheStale:
    """Tests for is_cache_stale()."""

    def test_stale_when_no_cache_entry(self, mocker):
        """
        When get_cache_age_seconds returns None (cache miss or error),
        is_cache_stale must return True to indicate the cache is stale.
        """
        mocker.patch("src.cache_service.get_cache_age_seconds", return_value=None)

        assert is_cache_stale() is True

    def test_not_stale_when_cache_is_fresh(self, mocker):
        """
        When the cache entry is fresh (within the max age), is_cache_stale must return False.
        """
        mocker.patch(
            "src.cache_service.get_cache_age_seconds", return_value=60
        )  # 1 minute old

        assert is_cache_stale(max_age_seconds=300) is False

    def test_stale_when_cache_exceeds_max_age(self, mocker):
        """
        When the cache entry exceeds the maximum age, is_cache_stale must return True.
        """
        mocker.patch(
            "src.cache_service.get_cache_age_seconds", return_value=360
        )  # > 5 minutes old

        assert is_cache_stale(max_age_seconds=300) is True

    def test_not_stale_exactly_at_boundary(self, mocker):
        """
        A cache entry aged exactly at max_age_seconds is considered fresh.
        """
        mocker.patch(
            "src.cache_service.get_cache_age_seconds", return_value=300
        )  # exactly 5 minutes old

        assert is_cache_stale(max_age_seconds=300) is False
