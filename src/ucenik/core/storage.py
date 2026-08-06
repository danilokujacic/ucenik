"""Raw file storage - MinIO locally, same S3 API in prod (just swap the endpoint).

Objects are keyed by content hash (`file_hash`), not filename or document id:
identical bytes uploaded twice - even to different subjects - share one
object. Document metadata (models/documents.py) is one row per upload, but
multiple Document rows can point at the same underlying object.
"""

import aioboto3
from botocore.exceptions import ClientError

from ucenik.core.config import settings

_session = aioboto3.Session()


def _client():
    return _session.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
    )


async def init_storage() -> None:
    """Create the bucket if it doesn't exist yet. Safe to call on every startup."""
    async with _client() as s3:
        try:
            await s3.head_bucket(Bucket=settings.s3_bucket)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchBucket"):
                raise
            await s3.create_bucket(Bucket=settings.s3_bucket)


async def upload_file(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    async with _client() as s3:
        await s3.put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)


async def download_file(key: str) -> bytes:
    async with _client() as s3:
        response = await s3.get_object(Bucket=settings.s3_bucket, Key=key)
        return await response["Body"].read()


async def delete_file(key: str) -> None:
    async with _client() as s3:
        await s3.delete_object(Bucket=settings.s3_bucket, Key=key)


async def file_exists(key: str) -> bool:
    async with _client() as s3:
        try:
            await s3.head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
