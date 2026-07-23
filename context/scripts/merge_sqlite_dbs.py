#!/usr/bin/env python3
"""
Merge two Sounduk SQLite DBs: base = live, add rows from S3 whose PKs are missing.

Usage:
  python merge_sqlite_dbs.py --live live.db --s3 s3.db --out merged.db
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from typing import Iterable


# Prefer parent-before-child for FK-ish order; unknown tables appended later.
PREFERRED_ORDER = [
    "users",
    "tracks",
    "albums",
    "payments",
    "import_jobs",
    "import_job_items",
    "admin_audit_log",
    "ip_blocks",
    "registration_limits",
]


def _tables(con: sqlite3.Connection) -> list[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _ordered_tables(names: Iterable[str]) -> list[str]:
    names_set = set(names)
    ordered = [t for t in PREFERRED_ORDER if t in names_set]
    ordered.extend(sorted(names_set - set(ordered)))
    return ordered


def _pk_columns(con: sqlite3.Connection, table: str) -> list[str]:
    cols = con.execute(f"PRAGMA table_info({table})").fetchall()
    # cid, name, type, notnull, dflt, pk
    pk = sorted([(c[5], c[1]) for c in cols if c[5] > 0])
    return [name for _, name in pk]


def _column_names(con: sqlite3.Connection, table: str) -> list[str]:
    return [c[1] for c in con.execute(f"PRAGMA table_info({table})").fetchall()]


def merge(live_path: str, s3_path: str, out_path: str) -> dict:
    shutil.copy2(live_path, out_path)
    out = sqlite3.connect(out_path)
    s3 = sqlite3.connect(f"file:{s3_path}?mode=ro", uri=True)
    out.execute("PRAGMA foreign_keys=OFF")

    live_tables = set(_tables(out))
    s3_tables = set(_tables(s3))
    common = _ordered_tables(live_tables & s3_tables)
    stats: dict[str, int] = {}

    for table in common:
        pk = _pk_columns(out, table)
        out_cols = _column_names(out, table)
        s3_cols = _column_names(s3, table)
        cols = [c for c in out_cols if c in s3_cols]
        if not cols:
            continue
        col_sql = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join("?" for _ in cols)

        if pk and all(p in cols for p in pk):
            existing = set()
            if len(pk) == 1:
                existing = {r[0] for r in out.execute(f'SELECT "{pk[0]}" FROM "{table}"')}
            else:
                pk_select = ", ".join(f'"{p}"' for p in pk)
                existing = {
                    tuple(r)
                    for r in out.execute(f'SELECT {pk_select} FROM "{table}"')
                }

            inserted = 0
            for row in s3.execute(f'SELECT {col_sql} FROM "{table}"'):
                row_map = dict(zip(cols, row))
                if len(pk) == 1:
                    key = row_map[pk[0]]
                    if key in existing:
                        continue
                else:
                    key = tuple(row_map[p] for p in pk)
                    if key in existing:
                        continue
                out.execute(
                    f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
                    [row_map[c] for c in cols],
                )
                existing.add(key)
                inserted += 1
            stats[table] = inserted
        else:
            # No PK: insert rows not already present (full-row compare on shared cols)
            existing = {
                tuple(r) for r in out.execute(f'SELECT {col_sql} FROM "{table}"')
            }
            inserted = 0
            for row in s3.execute(f'SELECT {col_sql} FROM "{table}"'):
                if tuple(row) in existing:
                    continue
                out.execute(
                    f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
                    list(row),
                )
                existing.add(tuple(row))
                inserted += 1
            stats[table] = inserted

    # library_revision = MAX(live, s3) for shared users
    if "users" in common and "library_revision" in _column_names(out, "users"):
        for uid, s3_rev in s3.execute("SELECT id, library_revision FROM users"):
            row = out.execute(
                "SELECT library_revision FROM users WHERE id=?", (uid,)
            ).fetchone()
            if row is None:
                continue
            live_rev = row[0] or 0
            s3_rev = s3_rev or 0
            if s3_rev > live_rev:
                out.execute(
                    "UPDATE users SET library_revision=? WHERE id=?",
                    (s3_rev, uid),
                )

    out.commit()

    summary = {
        "inserted": stats,
        "users": out.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "tracks": out.execute("SELECT COUNT(*) FROM tracks").fetchone()[0],
        "albums": out.execute("SELECT COUNT(*) FROM albums").fetchone()[0]
        if "albums" in live_tables
        else 0,
        "ilya_tracks": out.execute(
            "SELECT COUNT(*) FROM tracks WHERE user_id=6"
        ).fetchone()[0],
        "soan": out.execute(
            "SELECT id, username, email FROM users WHERE id=13 OR username='Soan'"
        ).fetchall(),
    }
    out.close()
    s3.close()
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", required=True)
    ap.add_argument("--s3", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    summary = merge(args.live, args.s3, args.out)
    print("merge_ok", summary)
    # Expected roughly: users>=13, tracks≈158+284=442, albums=10, ilya≈264
    if summary["users"] < 13:
        print("FAIL: expected Soan / >=13 users", file=sys.stderr)
        return 1
    if summary["tracks"] < 400:
        print("FAIL: unexpected track count", summary["tracks"], file=sys.stderr)
        return 1
    if not summary["soan"]:
        print("FAIL: Soan missing", file=sys.stderr)
        return 1
    if summary["ilya_tracks"] < 250:
        print("FAIL: Ilya tracks too low", summary["ilya_tracks"], file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
