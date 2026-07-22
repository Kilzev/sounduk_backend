#!/usr/bin/env python3
"""
Read-only аудит: строки tracks в БД vs объекты в S3 (Selectel).

Не делает UPDATE/DELETE. Только SELECT + head_object.

Запуск из корня sounduk_backend:
  python context/scripts/audit_tracks_s3.py
  python context/scripts/audit_tracks_s3.py --user-id 1
  python context/scripts/audit_tracks_s3.py --json-out /tmp/audit_tracks.json --csv-out /tmp/audit_tracks.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from botocore.exceptions import ClientError  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from s3_utils import S3_BUCKET_NAME, get_s3_client  # noqa: E402


def _head(client, key: str) -> tuple[str, int | None]:
    """Return (status, content_length). status: ok | missing | error:..."""
    try:
        head = client.head_object(Bucket=S3_BUCKET_NAME, Key=key)
        return "ok", int(head.get("ContentLength", 0))
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound", "403"}:
            # Some S3-compatible APIs return 403 for missing keys
            http = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if http == 404 or code in {"404", "NoSuchKey", "NotFound"}:
                return "missing", None
            if code == "403" or http == 403:
                return "forbidden", None
        return f"error:{code or type(exc).__name__}", None
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}", None


def _classify(
    file_path: str,
    cover_path: str | None,
    audio_status: str,
    cover_status: str | None,
    db_size: int,
    s3_size: int | None,
) -> str:
    tags: list[str] = []
    if file_path.startswith("uploads/"):
        tags.append("legacy_uploads_path")
    if audio_status == "missing":
        tags.append("audio_missing")
    elif audio_status == "ok":
        if s3_size is not None and db_size and s3_size != db_size:
            tags.append("size_mismatch")
    elif audio_status.startswith("error") or audio_status == "forbidden":
        tags.append(f"audio_{audio_status}")

    if cover_path:
        if cover_status == "missing":
            tags.append("cover_missing")
        elif cover_status and (
            cover_status.startswith("error") or cover_status == "forbidden"
        ):
            tags.append(f"cover_{cover_status}")

    if not tags:
        return "ok"
    # Primary label: prefer audio_missing for playability issues
    if "audio_missing" in tags and len(tags) == 1:
        return "audio_missing"
    if "cover_missing" in tags and "audio_missing" not in tags and len(tags) == 1:
        return "cover_missing"
    if tags == ["legacy_uploads_path"]:
        return "legacy_uploads_path"
    if tags == ["size_mismatch"]:
        return "size_mismatch"
    return "+".join(tags)


def audit(
    *,
    user_id: int | None,
    limit: int | None,
    sleep_ms: int,
    check_covers: bool,
) -> tuple[list[dict], Counter]:
    client = get_s3_client()
    db = SessionLocal()
    rows: list[dict] = []
    counts: Counter = Counter()

    try:
        query = db.query(models.Track).order_by(models.Track.created_at.desc())
        if user_id is not None:
            query = query.filter(models.Track.user_id == user_id)
        if limit is not None:
            query = query.limit(limit)

        tracks = query.all()
        total = len(tracks)
        print(f"auditing tracks={total} bucket={S3_BUCKET_NAME}", flush=True)

        for i, track in enumerate(tracks, start=1):
            file_path = str(track.file_path or "")
            cover_path = str(track.cover_path) if track.cover_path else None
            local = Path(file_path)

            if local.is_file():
                audio_status = "local"
                s3_size = local.stat().st_size
            else:
                audio_status, s3_size = _head(client, file_path)
                if sleep_ms:
                    time.sleep(sleep_ms / 1000.0)

            cover_status: str | None = None
            if check_covers and cover_path:
                cover_local = Path(cover_path)
                if cover_local.is_file():
                    cover_status = "local"
                else:
                    cover_status, _ = _head(client, cover_path)
                    if sleep_ms:
                        time.sleep(sleep_ms / 1000.0)
            elif not cover_path:
                cover_status = "none"

            label = _classify(
                file_path,
                cover_path,
                audio_status,
                cover_status,
                int(track.file_size or 0),
                s3_size,
            )
            counts[label] += 1

            row = {
                "track_id": track.id,
                "user_id": track.user_id,
                "title": track.title,
                "artist": track.artist,
                "file_path": file_path,
                "cover_path": cover_path,
                "file_size_db": track.file_size,
                "file_size_s3": s3_size,
                "audio_status": audio_status,
                "cover_status": cover_status,
                "status": label,
            }
            rows.append(row)

            if i % 50 == 0 or i == total:
                print(f"  progress {i}/{total}", flush=True)
    finally:
        db.close()

    return rows, counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only audit of track DB rows vs S3 objects"
    )
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=20,
        help="Pause between S3 head_object calls (default 20)",
    )
    parser.add_argument(
        "--no-covers",
        action="store_true",
        help="Skip cover_path checks",
    )
    parser.add_argument("--json-out", type=str, default=None)
    parser.add_argument("--csv-out", type=str, default=None)
    parser.add_argument(
        "--problems-only",
        action="store_true",
        help="Write only non-ok rows to output files",
    )
    args = parser.parse_args()

    rows, counts = audit(
        user_id=args.user_id,
        limit=args.limit,
        sleep_ms=args.sleep_ms,
        check_covers=not args.no_covers,
    )

    print("\n=== SUMMARY ===", flush=True)
    for key, value in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {key}: {value}", flush=True)
    print(f"  TOTAL: {sum(counts.values())}", flush=True)

    out_rows = [r for r in rows if r["status"] != "ok"] if args.problems_only else rows

    if args.json_out:
        path = Path(args.json_out)
        path.write_text(
            json.dumps(
                {"summary": dict(counts), "rows": out_rows},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"json written: {path} rows={len(out_rows)}", flush=True)

    if args.csv_out:
        path = Path(args.csv_out)
        fields = [
            "track_id",
            "user_id",
            "title",
            "artist",
            "file_path",
            "cover_path",
            "file_size_db",
            "file_size_s3",
            "audio_status",
            "cover_status",
            "status",
        ]
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(out_rows)
        print(f"csv written: {path} rows={len(out_rows)}", flush=True)

    problems = sum(v for k, v in counts.items() if k != "ok")
    # Exit 0 always for ops; problems are in the report
    print(f"problems={problems}", flush=True)


if __name__ == "__main__":
    main()
