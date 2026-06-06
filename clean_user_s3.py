import argparse
from typing import Iterable, Set

from database import SessionLocal
import models
from s3_utils import get_s3_client, S3_BUCKET_NAME


def _collect_keys_from_prefixes(s3, user_id: int) -> Set[str]:
    prefixes = (
        f"{user_id}/",
        f"uploads/{user_id}/",
        f"user_{user_id}/",
    )
    keys: Set[str] = set()
    paginator = s3.get_paginator("list_objects_v2")
    for prefix in prefixes:
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if key:
                    keys.add(key)
    return keys


def _normalize_possible_key(path_value: str) -> str | None:
    if not path_value:
        return None
    # Local absolute paths are not S3 keys.
    if path_value.startswith("/"):
        return None
    # Typical web URL to object storage -> extract key part after bucket host.
    if "://" in path_value:
        # Example: https://host/bucket/path/to/file.mp3
        parts = path_value.split("/", 3)
        if len(parts) < 4:
            return None
        return parts[3]
    return path_value


def _collect_keys_from_db(user_id: int) -> Set[str]:
    db = SessionLocal()
    try:
        keys: Set[str] = set()
        tracks = db.query(models.Track).filter(models.Track.user_id == user_id).all()
        for t in tracks:
            for value in (t.file_path, t.cover_path):
                if not value:
                    continue
                key = _normalize_possible_key(value)
                if key:
                    keys.add(key)
        return keys
    finally:
        db.close()


def _delete_keys(s3, keys: Iterable[str]) -> int:
    keys_list = list(keys)
    deleted = 0
    for i in range(0, len(keys_list), 1000):
        chunk = keys_list[i : i + 1000]
        s3.delete_objects(
            Bucket=S3_BUCKET_NAME,
            Delete={"Objects": [{"Key": k} for k in chunk]},
        )
        deleted += len(chunk)
    return deleted


def clean_user_s3(user_id: int, dry_run: bool = False) -> None:
    s3 = get_s3_client()

    prefix_keys = _collect_keys_from_prefixes(s3, user_id)
    db_keys = _collect_keys_from_db(user_id)
    keys = sorted(prefix_keys | db_keys)

    print(f"Bucket: {S3_BUCKET_NAME}")
    print(f"User ID: {user_id}")
    print(f"Matched by prefixes: {len(prefix_keys)}")
    print(f"Matched by DB paths: {len(db_keys)}")
    print(f"Total unique keys: {len(keys)}")

    if not keys:
        print("Nothing to delete.")
        return

    if dry_run:
        print("Dry-run mode. Keys that would be deleted:")
        for key in keys[:50]:
            print(f" - {key}")
        if len(keys) > 50:
            print(f"... and {len(keys) - 50} more")
        return

    token = f"DELETE USER {user_id}"
    confirm = input(f"Type '{token}' to confirm deletion: ").strip()
    if confirm != token:
        print("Operation cancelled.")
        return

    deleted = _delete_keys(s3, keys)
    print(f"Done. Deleted objects: {deleted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Delete S3 track objects for a specific user.",
    )
    parser.add_argument("--user-id", type=int, required=True, help="User ID to clean.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting.",
    )
    args = parser.parse_args()
    clean_user_s3(user_id=args.user_id, dry_run=args.dry_run)
