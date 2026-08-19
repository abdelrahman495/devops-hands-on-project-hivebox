"""
Unit tests for the storage_service module.

All MinIO network calls are mocked so no running instance is required.
"""

import io
import json
from datetime import UTC, datetime

import pytest
from minio.error import MinioException
from urllib3.exceptions import HTTPError

from src.storage_service import (
    MINIO_BUCKET,
    StorageError,
    ensure_bucket_exists,
    store_temperature_data,
)
from tests.helpers.prometheus import metric_value

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# ensure_bucket_exists
# ---------------------------------------------------------------------------


class TestEnsureBucketExists:
    """Tests for ensure_bucket_exists()."""

    def test_creates_bucket_when_absent(self, mocker):
        """
        When the bucket does not exist, make_bucket must be called
        with the configured bucket name.
        """
        mock_client = mocker.Mock()
        mock_client.bucket_exists.return_value = False
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        ensure_bucket_exists()

        mock_client.bucket_exists.assert_called_once_with(MINIO_BUCKET)
        mock_client.make_bucket.assert_called_once_with(MINIO_BUCKET)

    def test_does_not_create_bucket_when_present(self, mocker):
        """
        When the bucket already exists, make_bucket must not be called.
        """
        mock_client = mocker.Mock()
        mock_client.bucket_exists.return_value = True
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        ensure_bucket_exists()

        mock_client.bucket_exists.assert_called_once_with(MINIO_BUCKET)
        mock_client.make_bucket.assert_not_called()

    def test_raises_storage_error_on_minio_exception(self, mocker):
        """
        A MinioException while checking/creating the bucket must be
        caught internally and re-raised as a StorageError.
        """
        mock_client = mocker.Mock()
        mock_client.bucket_exists.side_effect = MinioException("unreachable")
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        with pytest.raises(StorageError, match="Failed to ensure bucket"):
            ensure_bucket_exists()

    def test_raises_storage_error_on_http_error(self, mocker):
        """
        An HTTPError while checking/creating the bucket must be
        caught internally and re-raised as a StorageError.
        """
        mock_client = mocker.Mock()
        mock_client.bucket_exists.side_effect = HTTPError("connection refused")
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        with pytest.raises(StorageError, match="Failed to ensure bucket"):
            ensure_bucket_exists()

    def test_storage_error_chains_original_exception(self, mocker):
        """
        The raised StorageError must preserve the original exception via
        exception chaining (`raise ... from exc`), so the root cause is
        never lost.
        """
        mock_client = mocker.Mock()
        original = MinioException("unreachable")
        mock_client.bucket_exists.side_effect = original
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        with pytest.raises(StorageError) as exc_info:
            ensure_bucket_exists()

        assert exc_info.value.__cause__ is original


# ---------------------------------------------------------------------------
# store_temperature_data
# ---------------------------------------------------------------------------


class TestStoreTemperatureData:
    """Tests for store_temperature_data()."""

    def test_ensures_bucket_before_writing(self, mocker):
        """
        The bucket must be ensured to exist before the object is written.
        """
        ensure_mock = mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        store_temperature_data(22.5, "Good")

        ensure_mock.assert_called_once_with()

    def test_does_not_write_when_bucket_ensure_fails(self, mocker):
        """
        If ensure_bucket_exists() raises, put_object must never be called
        and the StorageError must propagate unchanged.
        """
        mocker.patch(
            "src.storage_service.ensure_bucket_exists",
            side_effect=StorageError("Failed to ensure bucket"),
        )
        mock_client = mocker.Mock()
        mocker.patch("src.storage_service.get_client", return_value=mock_client)
        duration_count_before = metric_value(
            "hivebox_storage_operation_duration_seconds_count"
        )

        with pytest.raises(StorageError, match="Failed to ensure bucket"):
            store_temperature_data(22.5, "Good")

        mock_client.put_object.assert_not_called()
        assert (
            metric_value("hivebox_storage_operation_duration_seconds_count")
            == duration_count_before + 1
        )

    def test_writes_expected_object_name_format(self, mocker):
        """
        The object name must follow the
        temperatures/<YYYY>/<MM>/<DD>/T<HH>:<MM>:<SS>.<ffffff>Z.json
        pattern, derived from the current UTC time.
        """
        mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        fixed_now = datetime(2026, 6, 1, 12, 34, 56, 789123, tzinfo=UTC)
        mock_datetime = mocker.patch("src.storage_service.datetime")
        mock_datetime.now.return_value = fixed_now

        object_name = store_temperature_data(22.5, "Good")

        expected_name = "temperatures/2026/06/01/T12:34:56.789123Z.json"

        assert object_name == expected_name
        mock_datetime.now.assert_called_once_with(UTC)

        put_call = mock_client.put_object.call_args

        assert put_call.args[1] == expected_name

    def test_writes_correct_bucket_payload_and_content_type(self, mocker):
        """
        put_object must be called once with the configured bucket, a JSON
        payload containing the supplied temperature, status, and an ISO
        timestamp, plus the correct content length and content type.
        """
        mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        fixed_now = datetime(2026, 6, 1, 12, 34, 56, 789123, tzinfo=UTC)
        mock_datetime = mocker.patch("src.storage_service.datetime")
        mock_datetime.now.return_value = fixed_now

        store_temperature_data(22.5, "Good")

        mock_client.put_object.assert_called_once()

        put_call = mock_client.put_object.call_args
        stream = put_call.args[2]
        payload_bytes = stream.getvalue()
        data = json.loads(payload_bytes.decode("utf-8"))

        assert put_call.args[0] == MINIO_BUCKET
        assert isinstance(stream, io.BytesIO)
        assert data["average_temperature"] == 22.5
        assert data["status"] == "Good"
        assert data["stored_at"] == fixed_now.isoformat()
        assert put_call.args[3] == len(payload_bytes)
        assert put_call.kwargs["content_type"] == "application/json"

    def test_returns_object_name(self, mocker):
        """
        The function must return the generated object name on success.
        """
        mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        mocker.patch("src.storage_service.get_client", return_value=mock_client)
        duration_count_before = metric_value(
            "hivebox_storage_operation_duration_seconds_count"
        )

        result = store_temperature_data(22.5, "Good")

        assert result.startswith("temperatures/")
        assert result.endswith("Z.json")
        assert (
            metric_value("hivebox_storage_operation_duration_seconds_count")
            == duration_count_before + 1
        )

    def test_raises_storage_error_on_minio_exception(self, mocker):
        """
        A MinioException during put_object must be caught internally and
        re-raised as a StorageError.
        """
        mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        mock_client.put_object.side_effect = MinioException("write failed")
        mocker.patch("src.storage_service.get_client", return_value=mock_client)
        duration_count_before = metric_value(
            "hivebox_storage_operation_duration_seconds_count"
        )

        with pytest.raises(StorageError, match="Failed to store temperature snapshot"):
            store_temperature_data(22.5, "Good")

        assert (
            metric_value("hivebox_storage_operation_duration_seconds_count")
            == duration_count_before + 1
        )

    def test_raises_storage_error_on_http_error(self, mocker):
        """
        An HTTPError during put_object must be caught internally and
        re-raised as a StorageError.
        """
        mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        mock_client.put_object.side_effect = HTTPError("timeout")
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        with pytest.raises(StorageError, match="Failed to store temperature snapshot"):
            store_temperature_data(22.5, "Good")

    def test_storage_error_chains_original_exception(self, mocker):
        """
        The raised StorageError must preserve the original exception via
        exception chaining (`raise ... from exc`), so the root cause is
        never lost.
        """
        mocker.patch("src.storage_service.ensure_bucket_exists")
        mock_client = mocker.Mock()
        original = MinioException("write failed")
        mock_client.put_object.side_effect = original
        mocker.patch("src.storage_service.get_client", return_value=mock_client)

        with pytest.raises(StorageError) as exc_info:
            store_temperature_data(22.5, "Good")

        assert exc_info.value.__cause__ is original
