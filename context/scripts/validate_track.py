#!/usr/bin/env python3
"""Проверка целостности трека в БД и S3 (для диагностики битых импортов)."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

# Запуск из корня sounduk_backend: python context/scripts/validate_track.py <track_id>
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from mutagen import File as MutagenFile  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from database import SessionLocal  # noqa: E402
import models  # noqa: E402
import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
from s3_utils import S3_BUCKET_NAME, S3_ENDPOINT_URL, S3_REGION_NAME  # noqa: E402
from s3_utils import S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY  # noqa: E402


def _diagnostic_s3_client():
    cfg = Config(
        connect_timeout=30,
        read_timeout=120,
        retries={"max_attempts": 3, "mode": "adaptive"},
    )
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION_NAME,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        config=cfg,
    )


def _magic_label(head: bytes) -> str:
    if len(head) < 4:
        return "too_short"
    if head[:3] == b"ID3":
        return "id3_mp3"
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "mp3_frame_sync"
    if head[4:8] == b"ftyp":
        return "mp4_m4a"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.lstrip().startswith(b"<") or head.lstrip().startswith(b"{"):
        return "text_or_html"
    return f"unknown_hex={head[:8].hex()}"


def validate_track(db: Session, track_id: str) -> int:
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        print(f"FAIL track_id={track_id} not_found_in_db")
        return 1

    print(f"track_id={track.id}")
    print(f"title={track.title!r}")
    print(f"artist={track.artist!r}")
    print(f"user_id={track.user_id}")
    print(f"duration_db={track.duration}s")
    print(f"file_size_db={track.file_size}")
    print(f"file_path={track.file_path}")
    print(f"created_at={track.created_at}")

    local_path = Path(str(track.file_path))
    if local_path.is_file():
        raw = local_path.read_bytes()
        source = "local"
        file_size = len(raw)
        content_type = "local_file"
    else:
        s3 = _diagnostic_s3_client()
        key = str(track.file_path)
        try:
            head = s3.head_object(Bucket=S3_BUCKET_NAME, Key=key)
        except Exception as exc:
            print(f"FAIL s3_head error={exc}")
            return 2

        file_size = int(head.get("ContentLength", 0))
        content_type = head.get("ContentType", "unknown")
        print(f"s3_content_type={content_type}")
        print(f"s3_content_length={file_size}")

        if file_size != track.file_size:
            print(
                f"WARN size_mismatch db={track.file_size} s3={file_size}"
            )

        try:
            obj = s3.get_object(
                Bucket=S3_BUCKET_NAME,
                Key=key,
                Range="bytes=0-8191",
            )
            raw = obj["Body"].read()
        except Exception as exc:
            print(f"FAIL s3_get_range error={exc}")
            return 3
        source = "s3"

    magic = _magic_label(raw)
    print(f"source={source} magic={magic} sample_bytes={len(raw)}")

    issues: list[str] = []
    if file_size < 10_000:
        issues.append("file_too_small")
    if magic in {"text_or_html", "too_short", "unknown_hex"}:
        issues.append(f"bad_magic:{magic}")
    if magic == "text_or_html":
        preview = raw[:200].decode("utf-8", errors="replace")
        print(f"body_preview={preview!r}")

    parsed_duration = 0
    tmp_path: str | None = None
    mutagen_bytes: bytes | None = None

    if source == "local":
        mutagen_bytes = local_path.read_bytes()
    elif file_size <= 50 * 1024 * 1024:
        try:
            obj = s3.get_object(Bucket=S3_BUCKET_NAME, Key=str(track.file_path))
            mutagen_bytes = obj["Body"].read()
        except Exception as exc:
            issues.append(f"full_download_fail:{exc}")
    else:
        issues.append("mutagen_skipped_file_too_large")

    if mutagen_bytes is not None:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mutagen_bytes)
            tmp_path = tmp.name

    if tmp_path:
        try:
            audio = MutagenFile(tmp_path)
            if not audio:
                issues.append("mutagen_unparsed")
            elif getattr(audio, "info", None) and getattr(audio.info, "length", None):
                parsed_duration = max(0, int(audio.info.length))
                print(f"duration_mutagen={parsed_duration}s")
                if track.duration > 0 and abs(parsed_duration - track.duration) > 5:
                    issues.append(
                        f"duration_mismatch db={track.duration} "
                        f"mutagen={parsed_duration}"
                    )
            else:
                issues.append("mutagen_no_duration")
        except Exception as exc:
            issues.append(f"mutagen_error:{exc}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if issues:
        print(f"VERDICT=BROKEN issues={','.join(issues)}")
        return 4

    print("VERDICT=OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate track file in DB/S3")
    parser.add_argument("track_id", help="UUID трека")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        code = validate_track(db, args.track_id)
    finally:
        db.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
