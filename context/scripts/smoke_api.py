#!/usr/bin/env python3
"""Smoke-тест ключевых эндпоинтов (запускать на сервере из venv)."""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import urllib.error
import urllib.request

from auth_utils import create_access_token

BASE = "http://127.0.0.1:8000"
USER_ID = 6  # основной prod-пользователь


def req(method: str, path: str, token: str, timeout: float = 15) -> tuple[int, float, str]:
    url = f"{BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    request = urllib.request.Request(url, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read(512)
            ms = (time.perf_counter() - start) * 1000
            return resp.status, ms, body[:120].decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        ms = (time.perf_counter() - start) * 1000
        chunk = exc.read(200)
        return exc.code, ms, chunk.decode("utf-8", errors="replace")
    except Exception as exc:
        ms = (time.perf_counter() - start) * 1000
        return 0, ms, str(exc)


def main() -> int:
    token = create_access_token({"sub": str(USER_ID)})
    tests = [
        ("GET", "/"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/users/library-revision"),
        ("GET", "/api/users/storage"),
        ("GET", "/api/albums"),
        ("GET", "/api/tracks?limit=5"),
        ("GET", "/api/tracks?limit=50&cursor=ignored"),  # bad cursor → 400 ok
    ]

    print(f"smoke user_id={USER_ID}")
    failed = 0
    for item in tests:
        method, path = item[0], item[1]
        timeout = 35 if "albums" in path else 15
        code, ms, preview = req(method, path, token, timeout=timeout)
        ok = 200 <= code < 300 or (path.endswith("ignored") and code == 400)
        mark = "OK" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{mark} {method} {path} -> {code} {ms:.0f}ms {preview[:80]}")

    # albums latency check
    code, ms, _ = req("GET", "/api/albums", token, timeout=35)
    if ms > 5000:
        print(f"FAIL GET /api/albums slow {ms:.0f}ms (>5s)")
        failed += 1
    else:
        print(f"OK  GET /api/albums latency {ms:.0f}ms")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
