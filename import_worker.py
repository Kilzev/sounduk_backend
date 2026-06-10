#!/usr/bin/env python3
"""Отдельный процесс для YouTube/импорт job'ов (yt-dlp не блокирует API)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
logger = logging.getLogger("sounduk.import_worker")


async def main() -> None:
    from api.tracks import run_import_worker_loop

    logger.info("starting import worker pid=%s", os.getpid())
    await run_import_worker_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("import worker stopped")
