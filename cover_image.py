"""Normalize cover images for S3: square crop/pad, max side, WebP."""
from __future__ import annotations

from io import BytesIO

COVER_MAX_SIDE = 1000
WEBP_QUALITY = 80
# Vinyl labels sit on a dark disc; padding banners with white cuts a halo.
RADIO_PAD_BG = (18, 18, 22)


def normalize_cover_bytes(
    data: bytes,
    *,
    max_side: int = COVER_MAX_SIDE,
    quality: int = WEBP_QUALITY,
    square: str = "crop",
) -> tuple[bytes, str]:
    """Return (body, content_type). Falls back to original JPEG bytes if decode fails.

    square: ``crop`` (albums/tracks) or ``pad`` (radio logos / banners).
    """
    if not data:
        raise ValueError("empty cover")

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data, "image/jpeg"

    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except Exception:
        return data, "image/jpeg"

    flatten_bg = RADIO_PAD_BG if square == "pad" else (255, 255, 255)
    if image.mode in {"P", "PA"}:
        image = image.convert("RGBA")
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, flatten_bg)
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    if width > 0 and height > 0 and width != height:
        if square == "pad":
            side = max(width, height)
            padded = Image.new("RGB", (side, side), flatten_bg)
            padded.paste(image, ((side - width) // 2, (side - height) // 2))
            image = padded
        else:
            side = min(width, height)
            left = (width - side) // 2
            top = (height - side) // 2
            image = image.crop((left, top, left + side, top + side))

    side = image.size[0]
    if side > max_side:
        image = image.resize((max_side, max_side), Image.Resampling.LANCZOS)

    out = BytesIO()
    try:
        image.save(out, format="WEBP", quality=quality, method=4)
        body = out.getvalue()
        if body:
            return body, "image/webp"
    except Exception:
        pass

    jpeg_out = BytesIO()
    image.save(jpeg_out, format="JPEG", quality=max(quality, 85), optimize=True)
    return jpeg_out.getvalue(), "image/jpeg"
