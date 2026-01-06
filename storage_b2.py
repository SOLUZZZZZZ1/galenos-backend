# storage_b2.py — Backblaze B2 (S3-compatible) storage for Galenos
#
# Responsibilities:
# - Upload files to B2
# - Generate temporary download URLs (presigned)
# - Track size for quota control (10 GB per user)
#
# Notes:
# - Bucket must be PRIVATE
# - Credentials are read from environment variables
# - This module does NOT delete files (archiving handled elsewhere)
#
# ✅ Update (backend delete support):
# - Adds delete_prefix() to support hard-delete of patient history (B2 cleanup)

import os
import hashlib
import mimetypes

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


# ==============================
# ENV CONFIG (Render)
# ==============================
B2_ENDPOINT = os.getenv("B2_ENDPOINT")
B2_REGION = os.getenv("B2_REGION")
B2_BUCKET = os.getenv("B2_BUCKET")
B2_ACCESS_KEY_ID = os.getenv("B2_ACCESS_KEY_ID")
B2_SECRET_ACCESS_KEY = os.getenv("B2_SECRET_ACCESS_KEY")

if not all([B2_ENDPOINT, B2_REGION, B2_BUCKET, B2_ACCESS_KEY_ID, B2_SECRET_ACCESS_KEY]):
    raise RuntimeError("Missing Backblaze B2 environment variables.")


# ==============================
# S3 CLIENT (B2-compatible)
# ==============================
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{B2_ENDPOINT}",
    region_name=B2_REGION,
    aws_access_key_id=B2_ACCESS_KEY_ID,
    aws_secret_access_key=B2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
)


# ==============================
# HELPERS
# ==============================
def _guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


# ==============================
# PUBLIC API
# ==============================
def upload_bytes(
    *,
    user_id: int,
    category: str,
    object_id,
    filename: str,
    data: bytes,
) -> dict:
    """Upload bytes to Backblaze B2."""
    if not data:
        raise ValueError("Empty data")

    size_bytes = len(data)
    mime_type = _guess_mime(filename)
    sha256 = _sha256_bytes(data)

    file_key = f"prod/users/{user_id}/{category}/{object_id}/{filename}"

    try:
        s3.put_object(
            Bucket=B2_BUCKET,
            Key=file_key,
            Body=data,
            ContentType=mime_type,
            Metadata={
                "user_id": str(user_id),
                "category": category,
                "object_id": str(object_id),
                "sha256": sha256,
            },
        )
    except ClientError as e:
        raise RuntimeError(f"Upload failed: {e}")

    return {
        "file_key": file_key,
        "size_bytes": size_bytes,
        "mime_type": mime_type,
        "sha256": sha256,
    }


def upload_fileobj(
    *,
    user_id: int,
    category: str,
    object_id,
    filename: str,
    fileobj,
) -> dict:
    data = fileobj.read()
    return upload_bytes(
        user_id=user_id,
        category=category,
        object_id=object_id,
        filename=filename,
        data=data,
    )


def generate_presigned_url(
    *,
    file_key: str,
    expires_seconds: int = 300,
) -> str:
    try:
        return s3.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": B2_BUCKET, "Key": file_key},
            ExpiresIn=expires_seconds,
        )
    except ClientError as e:
        raise RuntimeError(f"Presigned URL failed: {e}")


def exists(file_key: str) -> bool:
    try:
        s3.head_object(Bucket=B2_BUCKET, Key=file_key)
        return True
    except ClientError:
        return False


def get_object_size(file_key: str) -> int:
    try:
        r = s3.head_object(Bucket=B2_BUCKET, Key=file_key)
        return int(r.get("ContentLength", 0))
    except ClientError as e:
        raise RuntimeError(f"Head object failed: {e}")


# ==============================
# DELETE API (used by hard delete)
# ==============================
def _list_keys(prefix: str) -> list[str]:
    """List all keys under a prefix."""
    keys: list[str] = []
    token = None

    while True:
        kwargs = {"Bucket": B2_BUCKET, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token

        resp = s3.list_objects_v2(**kwargs)
        for obj in (resp.get("Contents") or []):
            k = obj.get("Key")
            if k:
                keys.append(k)

        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    return keys


def _delete_keys(keys: list[str]) -> int:
    """Delete keys in batches (S3 limit: 1000 objects per request)."""
    if not keys:
        return 0

    deleted = 0
    chunk_size = 1000
    for i in range(0, len(keys), chunk_size):
        chunk = keys[i : i + chunk_size]
        try:
            s3.delete_objects(
                Bucket=B2_BUCKET,
                Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True},
            )
            deleted += len(chunk)
        except ClientError as e:
            raise RuntimeError(f"Delete failed: {e}")

    return deleted


def delete_prefix(prefix: str) -> int:
    """
    Delete EVERYTHING under a given prefix.
    Example:
      prefix = "prod/users/12/imaging/345/"
    """
    if not prefix:
        return 0
    keys = _list_keys(prefix)
    return _delete_keys(keys)
