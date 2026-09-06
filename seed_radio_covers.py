# seed_radio_covers.py
# На проде: cd /var/www/sounduk_backend && ./venv/bin/python seed_radio_covers.py --upgrade
# Скачивает логотипы каталога (не 16px favicon) и кладёт в S3 radio_covers/catalog/{id}.webp

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import re
import sys
from io import BytesIO
from urllib.parse import urljoin, urlparse
from typing import Any

import httpx

sys.path.insert(0, os.path.dirname(__file__))

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TIMEOUT = 20.0
MIN_SIDE = 128
GOOD_SIDE = 400
RECORD_API = "https://www.radiorecord.ru/api/stations/"
MYRADIO24_STATUS = "https://myradio24.com/users/{uid}/status.json"

# High-res brand art only. Google s2 is last-resort and often 16×16.
BRAND_LOGOS: dict[str, str] = {
    "SomaFM: Groove Salad": "https://somafm.com/img3/groovesalad-400.jpg",
    "SomaFM: Secret Agent": "https://somafm.com/img3/secretagent-400.jpg",
    "SomaFM: Drone Zone": "https://somafm.com/img3/dronezone-400.jpg",
    "BBC World Service": (
        "https://static.files.bbci.co.uk/sounds/web/sounds-web/img/"
        "sounds-apple-touch-icon.ead169771d.png"
    ),
    "BBC Radio 4": (
        "https://static.files.bbci.co.uk/sounds/web/sounds-web/img/"
        "sounds-apple-touch-icon.ead169771d.png"
    ),
    "NPR 24 Hour Program Stream": "https://media.npr.org/chrome/favicon/favicon-180x180.png",
    "90's Eurodance": "https://myradio24.com/users/5967/logo.jpg",
    "Dance Wave!": "https://dancewave.online/wp-content/uploads/2021/05/cropped-dwlogo_1400-1.png",
    "Radio Paradise (EU)": (
        "https://vsh-smedia.radioparadise.com/uploads/"
        "RP_Logo_Flat_HCR_Green_1_18a033c355.png"
    ),
    "Capital FM (UK)": "https://www.capitalfm.com/assets_v4r/capital/img/favicon-196x196.png",
    "РетроФМ": "https://retrofm.ru/_nuxt/logo.CcDe0IHs.png",
}

_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)


def stream_path_basename(url: str | None) -> str | None:
    if not url:
        return None
    path = urlparse(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1].strip().lower()
    return name or None


def myradio24_user_id(stream_url: str | None) -> str | None:
    if not stream_url:
        return None
    match = re.search(r"myradio24\.(?:com|org)(?::\d+)?/(\d+)", stream_url, re.I)
    return match.group(1) if match else None


def somafm_cover_url(name: str | None) -> str | None:
    if not name or not name.lower().startswith("somafm"):
        return None
    rest = name.split(":", 1)[-1].strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "", rest)
    if not slug:
        return None
    return f"https://somafm.com/img3/{slug}-400.jpg"


def index_record_logo_urls(payload: dict) -> dict[str, str]:
    """Map Record stream filename (rr_main96.aacp) → 600px colored icon.

    Skip generic HLS names like ``playlist.m3u8`` — they collide across stations.
    """
    result = payload.get("result") if isinstance(payload, dict) else None
    stations = []
    if isinstance(result, dict):
        stations = result.get("stations") or []
    elif isinstance(result, list):
        stations = result
    generic = {"playlist.m3u8", "index.m3u8", "listen.pls", "stream.mp3"}
    out: dict[str, str] = {}
    for station in stations:
        if not isinstance(station, dict):
            continue
        logo = (station.get("icon_fill_colored") or "").strip()
        if not logo:
            continue
        for key in ("stream_320", "stream_128", "stream_64"):
            base = stream_path_basename(station.get(key))
            if base and base not in generic:
                out[base] = logo
    return out


def image_max_side(data: bytes) -> int:
    try:
        from PIL import Image

        image = Image.open(BytesIO(data))
        image.load()
        w, h = image.size
        return max(w, h)
    except Exception:
        return 0


def _attr(tag: str, name: str) -> str | None:
    match = re.search(
        rf"""{name}\s*=\s*["']([^"']+)["']""", tag, re.IGNORECASE
    )
    return match.group(1) if match else None


def html_image_urls(html: str, base_url: str) -> list[str]:
    """Largest-looking icon / og:image first."""
    scored: list[tuple[int, str]] = []
    for tag in _LINK_RE.findall(html) + _META_RE.findall(html):
        rel = (_attr(tag, "rel") or "").lower()
        prop = (_attr(tag, "property") or _attr(tag, "name") or "").lower()
        href = _attr(tag, "href") or _attr(tag, "content")
        if not href:
            continue
        interesting = (
            "apple-touch-icon" in rel
            or rel in {"icon", "shortcut icon"}
            or prop in {"og:image", "og:image:url", "twitter:image"}
        )
        if not interesting:
            continue
        sizes = _attr(tag, "sizes") or ""
        side = 0
        for part in re.findall(r"(\d+)\s*x\s*(\d+)", sizes, re.I):
            side = max(side, int(part[0]), int(part[1]))
        if "apple-touch" in rel:
            side = max(side, 180)
        if "og:image" in prop or "twitter:image" in prop:
            side = max(side, 400)
        abs_url = urljoin(base_url, href)
        if abs_url.startswith("http"):
            scored.append((side, abs_url))
    scored.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _, url in scored:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _dedupe(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


async def _get(
    client: httpx.AsyncClient, url: str, *, accept: str
) -> httpx.Response | None:
    try:
        response = await client.get(
            url,
            headers={"User-Agent": UA, "Accept": accept},
            follow_redirects=True,
        )
        if response.status_code >= 400:
            return None
        return response
    except Exception:
        return None


async def download_image(client: httpx.AsyncClient, url: str) -> bytes | None:
    response = await _get(client, url, accept="image/*,*/*")
    if response is None:
        return None
    ctype = (response.headers.get("content-type") or "").lower()
    if "html" in ctype:
        return None
    body = response.content
    if len(body) < 64 or len(body) > 5 * 1024 * 1024:
        return None
    if image_max_side(body) < MIN_SIDE:
        return None
    return body


async def scrape_website_images(
    client: httpx.AsyncClient, website: str
) -> list[str]:
    parsed = urlparse(website if "://" in website else f"https://{website}")
    if not parsed.hostname:
        return []
    origin = f"{parsed.scheme or 'https'}://{parsed.hostname}"
    page = website if "://" in website else origin
    urls = [
        f"{origin}/apple-touch-icon.png",
        f"{origin}/apple-touch-icon-precomposed.png",
    ]
    response = await _get(client, page, accept="text/html,application/xhtml+xml")
    if response is not None:
        ctype = (response.headers.get("content-type") or "").lower()
        if "html" in ctype or not ctype:
            html = response.text[:120_000]
            urls = html_image_urls(html, str(response.url)) + urls
    return _dedupe(urls)


async def fetch_record_logos(client: httpx.AsyncClient) -> dict[str, str]:
    response = await _get(client, RECORD_API, accept="application/json")
    if response is None:
        print("WARN Record API unavailable")
        return {}
    try:
        payload = response.json()
    except Exception:
        print("WARN Record API JSON parse failed")
        return {}
    index = index_record_logo_urls(payload)
    print(f"Record logos indexed: {len(index)}")
    return index


async def myradio24_logo_url(
    client: httpx.AsyncClient, stream_url: str | None
) -> str | None:
    uid = myradio24_user_id(stream_url)
    if not uid:
        return None
    response = await _get(
        client, MYRADIO24_STATUS.format(uid=uid), accept="application/json"
    )
    if response is None:
        return f"https://myradio24.com/users/{uid}/logo.jpg"
    try:
        data = response.json()
    except Exception:
        return f"https://myradio24.com/users/{uid}/logo.jpg"
    logo = (data.get("logo") or "").strip()
    if not logo:
        return f"https://myradio24.com/users/{uid}/logo.jpg"
    return urljoin("https://myradio24.com/", logo)


async def pick_cover(
    client: httpx.AsyncClient,
    station: Any,
    record_logos: dict[str, str],
) -> tuple[str, bytes] | None:
    name = station.name or ""
    urls: list[str] = []

    record_logo = record_logos.get(stream_path_basename(station.stream_url) or "")
    if record_logo:
        urls.append(record_logo)
    if name in BRAND_LOGOS:
        urls.append(BRAND_LOGOS[name])
    somafm = somafm_cover_url(name)
    if somafm:
        urls.append(somafm)
    myradio = await myradio24_logo_url(client, station.stream_url)
    if myradio:
        urls.append(myradio)

    website = (station.website or "").strip()
    if website:
        urls.extend(await scrape_website_images(client, website))

    best: tuple[int, str, bytes] | None = None
    for url in _dedupe(urls):
        raw = await download_image(client, url)
        if not raw:
            continue
        side = image_max_side(raw)
        if best is None or side > best[0]:
            best = (side, url, raw)
        if side >= GOOD_SIDE:
            break
    if best is None:
        return None
    return best[1], best[2]


async def seed(*, upgrade: bool) -> None:
    from database import SessionLocal
    import models
    from cover_storage import apply_radio_cover

    db = SessionLocal()
    try:
        stations = (
            db.query(models.RadioStation).order_by(models.RadioStation.name).all()
        )
        ok = 0
        skip = 0
        fail = 0
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            record_logos = await fetch_record_logos(client)
            for station in stations:
                if station.cover_path and not upgrade:
                    skip += 1
                    continue
                picked = await pick_cover(client, station, record_logos)
                if picked is None:
                    print("MISS", station.name)
                    fail += 1
                    continue
                url, raw = picked
                try:
                    await apply_radio_cover(
                        station,
                        catalog=True,
                        cover_data=base64.b64encode(raw).decode("ascii"),
                    )
                    db.commit()
                    print("OK", station.name, image_max_side(raw), "<-", url)
                    ok += 1
                except Exception as exc:
                    db.rollback()
                    print("fail apply", station.name, url, exc)
                    fail += 1
                await asyncio.sleep(0.05)
        print(f"done ok={ok} skipped={skip} miss={fail}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Replace existing covers when a larger source is found",
    )
    args = parser.parse_args()
    asyncio.run(seed(upgrade=args.upgrade))


if __name__ == "__main__":
    main()
