#!/usr/bin/env bash
# Run on API host as root. Merges live DB with S3 latest.
set -euo pipefail

ROOT=/var/www/sounduk_backend
TS=$(date -u +%Y%m%d_%H%M%S)
LOCAL_BAK="$ROOT/backups_local"
PY="$ROOT/venv/bin/python"
MERGE_SCRIPT=/tmp/merge_sqlite_dbs.py
DB_BACKUP_SRC=/tmp/db_backup.py

cd "$ROOT"
mkdir -p "$LOCAL_BAK"

echo "== stop sounduk =="
systemctl stop sounduk
sleep 2

echo "== snapshot live =="
cp -a "$ROOT/database.db" "$LOCAL_BAK/database_live_premerge_${TS}.db"
LIVE_SNAP="$LOCAL_BAK/database_live_premerge_${TS}.db"

echo "== download S3 latest =="
$PY - <<PY
import os, sys
sys.path.insert(0, "$ROOT")
os.chdir("$ROOT")
from s3_utils import get_s3_client, S3_BUCKET_NAME
s3 = get_s3_client()
path = "$LOCAL_BAK/database_s3_latest_${TS}.db"
s3.download_file(S3_BUCKET_NAME, "backups/database_latest.db", path)
print("downloaded", path, os.path.getsize(path))
PY
S3_SNAP="$LOCAL_BAK/database_s3_latest_${TS}.db"

echo "== upload live premerge to S3 =="
$PY - <<PY
import os, sys
sys.path.insert(0, "$ROOT")
os.chdir("$ROOT")
from s3_utils import get_s3_client, S3_BUCKET_NAME
s3 = get_s3_client()
key = "backups/database_premerge_${TS}.db"
with open("$LIVE_SNAP", "rb") as f:
    s3.upload_fileobj(f, S3_BUCKET_NAME, key)
print("uploaded", key)
PY

echo "== merge =="
OUT="$LOCAL_BAK/database_merged_${TS}.db"
$PY "$MERGE_SCRIPT" --live "$LIVE_SNAP" --s3 "$S3_SNAP" --out "$OUT"

echo "== preserve live-only track check =="
$PY - <<PY
import sqlite3
live=sqlite3.connect("$LIVE_SNAP")
merged=sqlite3.connect("$OUT")
live_ids={r[0] for r in live.execute("SELECT id FROM tracks")}
merged_ids={r[0] for r in merged.execute("SELECT id FROM tracks")}
missing=live_ids-merged_ids
print("live_tracks", len(live_ids), "merged", len(merged_ids), "live_missing_in_merged", len(missing))
assert not missing, missing
users=merged.execute("SELECT COUNT(*) FROM users").fetchone()[0]
albums=merged.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
ilya=merged.execute("SELECT COUNT(*), COALESCE(SUM(file_size),0) FROM tracks WHERE user_id=6").fetchone()
soan=merged.execute("SELECT username,email FROM users WHERE id=13").fetchone()
print("users", users, "albums", albums, "ilya", ilya, "soan", soan)
assert users >= 13
assert albums >= 10
assert soan and soan[0]=="Soan"
assert ilya[0] >= 250
live.close(); merged.close()
print("validate_ok")
PY

echo "== atomic swap =="
cp -a "$OUT" "$ROOT/database.db.new"
os_replace() { python3 -c 'import os; os.replace("'"$ROOT"'/database.db.new", "'"$ROOT"'/database.db")'; }
os_replace
ls -la "$ROOT/database.db"

echo "== deploy fixed db_backup.py =="
if [[ -f "$DB_BACKUP_SRC" ]]; then
  cp -a "$ROOT/db_backup.py" "$ROOT/db_backup.py.bak.${TS}"
  cp -a "$DB_BACKUP_SRC" "$ROOT/db_backup.py"
fi

echo "== start sounduk =="
systemctl start sounduk
sleep 3
systemctl is-active sounduk

echo "== upload merged as latest =="
$PY - <<PY
import os, sys
sys.path.insert(0, "$ROOT")
os.chdir("$ROOT")
from db_backup import upload_db_to_s3
ok = upload_db_to_s3()
print("upload_ok", ok)
PY

echo "== smoke =="
curl -sS -o /dev/null -w "docs=%{http_code}\n" -H "Accept: application/json" https://api.sounduk.ru/docs || curl -sS -o /dev/null -w "docs_local=%{http_code}\n" -H "Accept: application/json" http://127.0.0.1:8000/docs
$PY - <<PY
import sqlite3
con=sqlite3.connect("$ROOT/database.db")
print("FINAL", {
  "users": con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
  "tracks": con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0],
  "albums": con.execute("SELECT COUNT(*) FROM albums").fetchone()[0],
  "ilya": con.execute("SELECT COUNT(*), round(SUM(file_size)/1024.0/1024/1024,3) FROM tracks WHERE user_id=6").fetchone(),
  "soan": con.execute("SELECT id,username,email FROM users WHERE id=13").fetchone(),
})
con.close()
PY
echo "MERGE_DONE ts=$TS"
