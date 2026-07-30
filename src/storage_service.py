"""
Storage service using MinIO (S3-compatible) for persisting temperature snapshots.

Each snapshot is stored as a JSON object under the `temperatures/` prefix
inside the configured bucket. The bucket is created automatically on first use.
"""

import io
import json
import os
from datetime import datetime, timezone

from minio import Minio
from minio.error import MinioException
from urllib3.exceptions import HTTPError

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "hivebox")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

_client = None


class StorageError(Exception):
    """Raised when a MinIO operation fails for any reason."""


def get_client():
    """
    Returns a lazily-initialized singleton MinIO client.
    """
    global _client  # pylint: disable=global-statement
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
    return _client


def ensure_bucket_exists():
    """
    Creates `MINIO_BUCKET` if it does not already exist.

    Raises:
        StorageError: If MinIO is unreachable or the bucket check/creation fails.
    """
    client = get_client()
    try:
        if not client.bucket_exists(MINIO_BUCKET):
            client.make_bucket(MINIO_BUCKET)
    except (MinioException, HTTPError) as exc:
        raise StorageError(
            f"Failed to ensure bucket '{MINIO_BUCKET}' exists: {exc}"
        ) from exc


def store_temperature_data(avg_temp, status):
    """
    Persists a temperature snapshot as a JSON object in MinIO.

    The object is written under the path:
        temperatures/<YYYY>/<MM>/<DD>/T<HH>:<MM>:<SS>.<ffffff>Z.json

    Args:
        avg_temp (float): The average temperature value in Celsius.
        status (str): The human-readable temperature status.

    Returns:
        str:
            The full object name (path) under which the data was stored.

    Raises:
        StorageError: If MinIO is unreachable or the write operation fails.
    """
    ensure_bucket_exists()

    now = datetime.now(timezone.utc)
    object_name = f"temperatures/{now.strftime('%Y/%m/%d/T%H:%M:%S.%fZ')}.json"

    payload = json.dumps(
        {
            "average_temperature": avg_temp,
            "status": status,
            "stored_at": now.isoformat(),
        }
    ).encode("utf-8")

    client = get_client()
    try:
        client.put_object(
            MINIO_BUCKET,
            object_name,
            io.BytesIO(payload),
            len(payload),
            content_type="application/json",
        )
    except (MinioException, HTTPError) as exc:
        raise StorageError(
            f"Failed to store temperature snapshot to MinIO: {exc}"
        ) from exc

    return object_name
