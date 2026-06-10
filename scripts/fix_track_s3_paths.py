#!/usr/bin/env python3
"""
Исправляет file_path uploads/... → tracks/{user_id}/{id}.mp3,
если файл уже лежит в S3 под tracks/ (частый случай после миграции).
Бэкап database.db на S3 — только метаданные, не MP3.
"""
from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv

load_dotenv(os.path.join(BASE_DIR, ".env"))

from botocore.exceptions import ClientError

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from library_sync import bump_library_revision  # noqa: E402
from s3_utils import S3_BUCKET_NAME, get_s3_upload_client  # noqa: E402


def _s3_exists(client, key: str) -> bool:
    try:
        client.head_object(Bucket=S3_BUCKET_NAME, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def _resolve_s3_key(client, user_id: int, track_id: str) -> str | None:
    for ext in (".mp3", ".m4a", ".flac"):
        key = f"tracks/{user_id}/{track_id}{ext}"
        if _s3_exists(client, key):
            return key
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix track file_path from uploads/ to tracks/ in S3")
    parser.add_argument("--apply", action="store_true", help="Write changes to database.db")
    parser.add_argument("--user-id", type=int, default=None, help="Limit to one user")
    args = parser.parse_args()

    client = get_s3_upload_client()
    db = SessionLocal()
    fixed = 0
    already_ok = 0
    missing = 0
    touched_users: set[int] = set()

    try:
        query = db.query(models.Track).filter(models.Track.file_path.like("uploads/%"))
        if args.user_id is not None:
            query = query.filter(models.Track.user_id == args.user_id)

        for track in query.all():
            current = str(track.file_path)
            if current.startswith("tracks/"):
                already_ok += 1
                continue

            new_key = _resolve_s3_key(client, track.user_id, track.id)
            if not new_key:
                missing += 1
                continue

            print(f"{'APPLY' if args.apply else 'DRY'} {track.id}: {current} -> {new_key}")
            if args.apply:
                track.file_path = new_key
                touched_users.add(track.user_id)
            fixed += 1

        if args.apply and fixed:
            for user_id in touched_users:
                bump_library_revision(db, user_id)
            db.commit()

        print(
            f"done fixed={fixed} missing_in_s3={missing} "
            f"already_tracks_prefix={already_ok} apply={args.apply}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
