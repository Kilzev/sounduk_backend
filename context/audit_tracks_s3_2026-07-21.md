# Audit: tracks DB vs S3 (Selectel)

**Date:** 2026-07-21  
**Host:** `178.72.184.68` (`emelda`), path `/var/www/sounduk_backend`  
**Tool:** `context/scripts/audit_tracks_s3.py` (read-only: SELECT + head_object)  
**Bucket:** `sounduk`

## Summary

| Status | Count |
|--------|------:|
| ok | 158 |
| legacy_uploads_path + audio_missing + cover_missing | 109 |
| legacy_uploads_path + audio_missing | 41 |
| legacy_uploads_path (audio OK at uploads/ key) | 5 |
| legacy_uploads_path + cover_missing (audio OK) | 2 |
| **TOTAL** | **315** |
| **problems** | **157** |
| **audio_missing (unplayable cloud)** | **150** |

Artifacts on server: `/tmp/audit_tracks_s3.json`, `/tmp/audit_tracks_s3.csv` (problems-only).

## Findings

1. All problem rows still use legacy keys `uploads/{user_id}/{track_id}.mp3` (not `tracks/...`).
2. Dry-run `scripts/fix_track_s3_paths.py` (no `--apply`): **0** remappable — objects also missing under `tracks/{user_id}/{id}.{mp3,m4a,flac}`. So this is **not** a path-prefix typo; **S3 objects are gone**.
3. Covers can still appear in the app via disk/mem cache while audio 404s — matches user reports.
4. `/token` still succeeds for these rows (DB metadata present); play fails at S3 GET.

## Remediation (NOT done — needs explicit approval)

- Do **not** mass-DELETE DB rows to “clean” the library without product decision.
- Options: ask users to re-upload; restore MP3 from an external backup if any; optional soft-flag `is_playable` later.
- The 7 `uploads/` keys that still head OK could later be migrated to `tracks/` via `fix_track_s3_paths.py --apply` after a focused dry-run/confirm.

## Safety

No UPDATE/DELETE on `database.db`. No `clean_s3` / admin cleanup.
